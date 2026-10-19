import asyncio
import io
import math
import os
import shlex
import struct
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final

from mcp.server.mcpserver import Image
from PIL import ExifTags, Image as PillowImage, ImageMath, UnidentifiedImageError

from config.constants import BYTES_PER_MIB
from domain.exceptions import InvalidArgumentError, WorkspaceFileError
from domain.workspace import resolve_workspace_path, to_workspace_relative
from infrastructure.fs.beneath import open_beneath
from services.file_operations import read_all, require_regular_file, run_file_operation
from services.image_constants import FILE_VIEW_IMAGE_FORMATS, FILE_VIEW_IMAGE_JPEG_QUALITY, FILE_VIEW_IMAGE_LOSSLESS_MAX_BASE64_BYTES, FILE_VIEW_IMAGE_MAX_BASE64_BYTES, FILE_VIEW_IMAGE_MAX_CONCURRENT_DECODES, FILE_VIEW_IMAGE_MAX_INPUT_BYTES, FILE_VIEW_IMAGE_MAX_PIXELS, FILE_VIEW_IMAGE_MIN_DIMENSION, FILE_VIEW_IMAGE_SHRINK_FACTOR, FILE_VIEW_IMAGE_STRIP_PIXELS
from utils.logger import logger


_BYTES_PER_KIB: Final[int] = 1024
_OPAQUE_ALPHA: Final[int] = 255
_SIXTEEN_TO_EIGHT_BIT_DIVISOR: Final[int] = 256
_LANCZOS_SUPPORT: Final[float] = 3.0
_ALPHA_MODES: Final[frozenset[str]] = frozenset({"LA", "RGBA"})
_LOSSLESS_FORMATS: Final[frozenset[str]] = frozenset({"png", "gif"})
_SWAPPED_ORIENTATIONS: Final[frozenset[int]] = frozenset({5, 6, 7, 8})
_ORIENTATION_TRANSPOSES: Final[dict[int, PillowImage.Transpose]] = {
    2: PillowImage.Transpose.FLIP_LEFT_RIGHT,
    3: PillowImage.Transpose.ROTATE_180,
    4: PillowImage.Transpose.FLIP_TOP_BOTTOM,
    5: PillowImage.Transpose.TRANSPOSE,
    6: PillowImage.Transpose.ROTATE_270,
    7: PillowImage.Transpose.TRANSVERSE,
    8: PillowImage.Transpose.ROTATE_90,
}

PillowImage.MAX_IMAGE_PIXELS = FILE_VIEW_IMAGE_MAX_PIXELS


class ImageViewService:
    def __init__(self) -> None:
        self._decode_semaphore = asyncio.Semaphore(FILE_VIEW_IMAGE_MAX_CONCURRENT_DECODES)

    async def view(self, path: str, max_dimension: int, region: Sequence[int] | None) -> list[Image | str]:
        target = resolve_workspace_path(path)
        await self._decode_semaphore.acquire()
        decode_task = asyncio.create_task(run_file_operation(path, self._view_sync, target, path, max_dimension, region))
        decode_task.add_done_callback(self._release_decode_slot)
        return await asyncio.shield(decode_task)

    def _release_decode_slot(self, decode_task: asyncio.Task[list[Image | str]]) -> None:
        self._decode_semaphore.release()
        if not decode_task.cancelled():
            decode_task.exception()

    def _view_sync(self, target: PurePosixPath, path: str, max_dimension: int, region: Sequence[int] | None) -> list[Image | str]:
        with open_beneath(to_workspace_relative(target), os.O_RDONLY, path) as file_descriptor:
            size_bytes = require_regular_file(file_descriptor, path).st_size
            if size_bytes > FILE_VIEW_IMAGE_MAX_INPUT_BYTES:
                raise self._oversized_image_error(target, path, f"is {self._format_size(size_bytes)}, above the {self._format_size(FILE_VIEW_IMAGE_MAX_INPUT_BYTES)} limit")

            image_data = read_all(file_descriptor, path, FILE_VIEW_IMAGE_MAX_INPUT_BYTES)

        return self._prepare_view(image_data, target, path, max_dimension, region)

    def _prepare_view(self, image_data: bytes, target: PurePosixPath, path: str, max_dimension: int, region: Sequence[int] | None) -> list[Image | str]:
        if not image_data:
            raise WorkspaceFileError(f"{path} is an empty file, so there is no image to show.")

        try:
            with PillowImage.open(io.BytesIO(image_data), formats=FILE_VIEW_IMAGE_FORMATS) as image:
                image_format = "jpeg" if image.format == "MPO" else str(image.format).lower()
                return self._render_view(image, image_data, image_format, target, path, max_dimension, region)
        except PillowImage.DecompressionBombError as error:
            raise self._oversized_image_error(target, path, f"has more than {FILE_VIEW_IMAGE_MAX_PIXELS // 1_000_000} megapixels") from error
        except UnidentifiedImageError as error:
            raise WorkspaceFileError(f"Cannot decode {path}. It is not PNG, JPEG, WebP or GIF, or its header is corrupt. Convert it with shell_execute first.") from error
        except (EOFError, IndexError, KeyError, OSError, SyntaxError, ValueError, struct.error) as error:
            raise WorkspaceFileError(f"Cannot decode {path}: {error or type(error).__name__}. The file looks truncated or corrupt.") from error

    def _render_view(self, image: PillowImage.Image, image_data: bytes, image_format: str, target: PurePosixPath, path: str, max_dimension: int, region: Sequence[int] | None) -> list[Image | str]:
        raw_width, raw_height = image.size
        if raw_width * raw_height > FILE_VIEW_IMAGE_MAX_PIXELS:
            raise self._oversized_image_error(target, path, f"is {raw_width}x{raw_height}, above the {FILE_VIEW_IMAGE_MAX_PIXELS} pixel limit")

        frame_count = getattr(image, "n_frames", 1)
        if image_format != "jpeg":
            image.load()

        orientation = self._read_orientation(image, path)

        is_swapped = orientation in _SWAPPED_ORIENTATIONS
        width, height = (raw_height, raw_width) if is_swapped else (raw_width, raw_height)
        extra_notes = [f"The file has {frame_count} frames. Only the first one is shown."] if frame_count > 1 else []
        original_label = f"{width}x{height} {image_format.upper()} ({self._format_size(len(image_data))})"
        is_passthrough = region is None and orientation == 1 and frame_count == 1 and image.mode != "CMYK" and max(width, height) <= max_dimension and self._fits_base64(len(image_data))
        if is_passthrough:
            image.load()
            return [Image(data=image_data, format=image_format), f"Image {path} is {original_label}, shown at full resolution. The file is unchanged."]

        left, top, region_width, region_height = self._clamp_region(region, width, height, path)
        scale = min(max_dimension / max(region_width, region_height), 1.0)
        shown_size = (max(round(region_width * scale), 1), max(round(region_height * scale), 1))
        raw_output_size = (shown_size[1], shown_size[0]) if is_swapped else shown_size
        raw_box = self._oriented_to_raw_box((left, top, left + region_width, top + region_height), orientation, raw_width, raw_height)

        box_width, box_height = raw_box[2] - raw_box[0], raw_box[3] - raw_box[1]
        image.draft(None, (math.ceil(raw_width * raw_output_size[0] / box_width), math.ceil(raw_height * raw_output_size[1] / box_height)))
        ratio_x, ratio_y = image.width / raw_width, image.height / raw_height
        source_box = (raw_box[0] * ratio_x, raw_box[1] * ratio_y, min(raw_box[2] * ratio_x, image.width), min(raw_box[3] * ratio_y, image.height))
        image.load()

        view = self._resample_in_strips(image, source_box, raw_output_size, self._resamplable_mode(image))
        if orientation != 1:
            view = view.transpose(_ORIENTATION_TRANSPOSES[orientation])

        shown_data, shown_format, view = self._encode_view(view, image_format in _LOSSLESS_FORMATS, path)
        scale_x, scale_y = region_width / view.width, region_height / view.height
        is_downscaled = view.width < region_width or view.height < region_height
        shown_label = f"{view.width}x{view.height} {shown_format.upper()} ({self._format_size(len(shown_data))})"
        if region is None:
            summary = f"Image {path} is {original_label}, shown as {shown_label}"
        else:
            summary = f"Region x={left} y={top} width={region_width} height={region_height} of image {path} ({original_label}) shown as {shown_label}"

        if is_downscaled:
            summary += f", scaled down (original x = {left} + shown x * {scale_x:.6g}, y = {top} + shown y * {scale_y:.6g})"
        elif region is None:
            summary += " at full resolution"
        else:
            summary += f" at full resolution (original x = {left} + shown x, y = {top} + shown y)"

        notes = [f"{summary}. The file is unchanged.", *extra_notes]
        if orientation != 1:
            notes.append("The EXIF orientation was applied, so sizes and region coordinates refer to the upright image.")

        if is_downscaled:
            notes.append(f"To read fine detail, call file_view_image again with region=[x, y, width, height] in original pixels. A region up to {max_dimension}x{max_dimension} is shown at full resolution.")

        logger.info(f"Prepared image view path={path} original={width}x{height} region={left},{top},{region_width}x{region_height} shown={view.width}x{view.height} format={shown_format} bytes_before={len(image_data)} bytes_after={len(shown_data)}")
        return [Image(data=shown_data, format=shown_format), " ".join(notes)]

    @staticmethod
    def _read_orientation(image: PillowImage.Image, path: str) -> int:
        try:
            orientation = image.getexif().get(ExifTags.Base.Orientation, 1)
        except (EOFError, IndexError, KeyError, OSError, SyntaxError, TypeError, ValueError, struct.error) as error:
            logger.debug(f"Ignored unreadable EXIF of image {path}: {error}")
            return 1

        if isinstance(orientation, tuple) and orientation:
            orientation = orientation[0]

        return orientation if isinstance(orientation, int) and orientation in _ORIENTATION_TRANSPOSES else 1

    @staticmethod
    def _clamp_region(region: Sequence[int] | None, width: int, height: int, path: str) -> tuple[int, int, int, int]:
        if region is None:
            return 0, 0, width, height

        left, top, region_width, region_height = region
        if left < 0 or top < 0 or region_width < 1 or region_height < 1:
            raise InvalidArgumentError(f"region must be [x, y, width, height] with x and y at least 0 and width and height at least 1, got {list(region)}.")

        if left >= width or top >= height:
            raise InvalidArgumentError(f"The region starts at x={left} y={top}, outside {path}, which is {width}x{height}. Pass coordinates inside the image.")

        return left, top, min(region_width, width - left), min(region_height, height - top)

    @staticmethod
    def _oriented_to_raw_box(box: tuple[int, int, int, int], orientation: int, raw_width: int, raw_height: int) -> tuple[int, int, int, int]:
        left, top, right, bottom = box
        raw_boxes = {
            1: (left, top, right, bottom),
            2: (raw_width - right, top, raw_width - left, bottom),
            3: (raw_width - right, raw_height - bottom, raw_width - left, raw_height - top),
            4: (left, raw_height - bottom, right, raw_height - top),
            5: (top, left, bottom, right),
            6: (top, raw_height - right, bottom, raw_height - left),
            7: (raw_width - bottom, raw_height - right, raw_width - top, raw_height - left),
            8: (raw_width - bottom, left, raw_width - top, right),
        }
        return raw_boxes[orientation]

    @staticmethod
    def _resamplable_mode(image: PillowImage.Image) -> str:
        if image.mode in _ALPHA_MODES:
            return image.mode

        if image.has_transparency_data:
            return "RGBA"

        return "L" if image.mode == "1" or image.mode.startswith(("L", "I")) else "RGB"

    @staticmethod
    def _to_resamplable(image: PillowImage.Image, target_mode: str) -> PillowImage.Image:
        if not image.mode.startswith("I"):
            return image if image.mode == target_mode else image.convert(target_mode)

        wide_image = image.convert("I")
        gray_image = wide_image.point(lambda value: value / _SIXTEEN_TO_EIGHT_BIT_DIVISOR).convert("L")
        transparent_value = image.info.get("transparency")
        if target_mode != "RGBA" or not isinstance(transparent_value, int):
            return gray_image.convert(target_mode)

        opaque_mask = ImageMath.lambda_eval(lambda arguments: (arguments["pixels"] != transparent_value) * _OPAQUE_ALPHA, pixels=wide_image)
        if not isinstance(opaque_mask, PillowImage.Image):
            raise WorkspaceFileError(f"Cannot build the transparency mask of a {image.mode} image: expected an image, got {type(opaque_mask).__name__}.")
        alpha_image = opaque_mask.convert("L")
        rgba_image = gray_image.convert("RGBA")
        rgba_image.putalpha(alpha_image)
        return rgba_image

    def _resample_in_strips(self, image: PillowImage.Image, source_box: tuple[float, float, float, float], output_size: tuple[int, int], target_mode: str) -> PillowImage.Image:
        left, top, right, bottom = source_box
        output_width, output_height = output_size
        scale_x, scale_y = (right - left) / output_width, (bottom - top) / output_height
        if (scale_x, scale_y) == (1.0, 1.0) and all(float(edge).is_integer() for edge in source_box):
            return self._to_resamplable(image.crop((int(left), int(top), int(right), int(bottom))), target_mode)

        margin_x = math.ceil(_LANCZOS_SUPPORT * max(scale_x, 1.0)) + 1
        margin_y = math.ceil(_LANCZOS_SUPPORT * max(scale_y, 1.0)) + 1
        crop_left, crop_right = max(math.floor(left) - margin_x, 0), min(math.ceil(right) + margin_x, image.width)
        rows_per_strip = max(int(FILE_VIEW_IMAGE_STRIP_PIXELS / (crop_right - crop_left) / scale_y), 1)

        output = PillowImage.new(target_mode, output_size)
        for output_top in range(0, output_height, rows_per_strip):
            output_bottom = min(output_top + rows_per_strip, output_height)
            source_top = top + output_top * scale_y
            source_bottom = bottom if output_bottom == output_height else top + output_bottom * scale_y
            crop_top, crop_bottom = max(math.floor(source_top) - margin_y, 0), min(math.ceil(source_bottom) + margin_y, image.height)
            strip = self._to_resamplable(image.crop((crop_left, crop_top, crop_right, crop_bottom)), target_mode)
            strip_box = (left - crop_left, source_top - crop_top, right - crop_left, min(source_bottom - crop_top, strip.height))
            output.paste(strip.resize((output_width, output_bottom - output_top), PillowImage.Resampling.LANCZOS, box=strip_box), (0, output_top))

        return output

    def _encode_view(self, view: PillowImage.Image, prefers_lossless: bool, path: str) -> tuple[bytes, str, PillowImage.Image]:
        if view.mode in _ALPHA_MODES and view.getchannel("A").getextrema() == (_OPAQUE_ALPHA, _OPAQUE_ALPHA):
            view = view.convert("L" if view.mode == "LA" else "RGB")

        candidate_formats: tuple[str, ...]
        if view.mode in _ALPHA_MODES:
            candidate_formats = ("png",)
        elif prefers_lossless:
            candidate_formats = ("png", "jpeg")
        else:
            candidate_formats = ("jpeg",)

        while True:
            for candidate_format in candidate_formats:
                buffer = io.BytesIO()
                if candidate_format == "png":
                    view.save(buffer, "PNG")
                else:
                    view.save(buffer, "JPEG", quality=FILE_VIEW_IMAGE_JPEG_QUALITY, subsampling="4:4:4")

                budget = FILE_VIEW_IMAGE_LOSSLESS_MAX_BASE64_BYTES if candidate_format == "png" and len(candidate_formats) > 1 else FILE_VIEW_IMAGE_MAX_BASE64_BYTES
                if self._fits_base64(buffer.tell(), budget):
                    return buffer.getvalue(), candidate_format, view

            if max(view.size) <= FILE_VIEW_IMAGE_MIN_DIMENSION:
                raise WorkspaceFileError(f"{path} does not fit in the {FILE_VIEW_IMAGE_MAX_BASE64_BYTES // 1_000_000} MB response limit even at {view.width}x{view.height}. Pass region to view a smaller part.")

            view = view.resize((max(int(view.width * FILE_VIEW_IMAGE_SHRINK_FACTOR), 1), max(int(view.height * FILE_VIEW_IMAGE_SHRINK_FACTOR), 1)), PillowImage.Resampling.LANCZOS)

    @staticmethod
    def _fits_base64(size_bytes: int, budget: int = FILE_VIEW_IMAGE_MAX_BASE64_BYTES) -> bool:
        return 4 * math.ceil(size_bytes / 3) <= budget

    @staticmethod
    def _oversized_image_error(target: PurePosixPath, path: str, reason: str) -> WorkspaceFileError:
        return WorkspaceFileError(f"{path} {reason}, so it is too large to shrink safely in memory. Shrink or crop it with shell_execute first, for example convert {shlex.quote(str(target))} -resize 2000x2000 -quality 85 {shlex.quote(str(target.with_suffix('.small.jpg')))} (magick on ImageMagick 7), then view the result.")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes >= BYTES_PER_MIB:
            return f"{size_bytes / BYTES_PER_MIB:.1f} MiB"

        if size_bytes >= _BYTES_PER_KIB:
            return f"{size_bytes / _BYTES_PER_KIB:.0f} KiB"

        return f"{size_bytes} bytes"
