import asyncio
import re
import shlex
from collections.abc import Callable
from secrets import randbelow
from typing import Any, Final
from uuid import uuid4

import aiodocker
from aiodocker.exceptions import DockerError
from aiohttp import ClientError

from config.constants import ERROR_PREVIEW_CHARS, OUTPUT_CHAR_LIMIT_DEFAULT, SANDBOX_PYTHON_PATH
from domain.exceptions import InvalidArgumentError, SandboxError, SandboxExecError, SandboxRestartedError, SandboxUnavailableError
from domain.generation import SandboxGeneration
from domain.models import ShellResult
from domain.workspace import resolve_command_cwd
from infrastructure.docker.constants import DOCKER_CLIENT_CONNECTION_ERROR_STATUS, DOCKER_CONTAINER_GONE_STATUSES, EXEC_CANCEL_KILL_TIMEOUT_SECONDS, EXEC_GROUP_TAG_COUNT, EXEC_GROUP_TAG_MIN, EXEC_KILL_EXIT_CODE, EXEC_TIMEOUT_BACKSTOP_SECONDS, EXEC_TIMEOUT_EXIT_CODE, EXEC_TIMEOUT_KILL_GRACE_SECONDS, SANDBOX_CONNECT_ATTEMPTS, SANDBOX_RECONNECT_DELAY_SECONDS
from sandbox_scripts import EXEC_KILL_SCRIPT
from sandbox_scripts.exec_kill import MARKER_VARIABLE
from utils.logger import logger
from utils.output import OutputCapture


_STDOUT_STREAM: Final[int] = 1
_CONNECTION_FAILURE_REASON: Final[str] = "the connection to it failed (details are in the server log)"
_CONTAINER_GONE_REASON: Final[str] = "the container was not found or is not running"
_DOCKER_API_FAILURE_REASON: Final[str] = "the Docker API returned an error (details are in the server log)"
_CONTAINER_ID_PREVIEW_CHARS: Final[int] = 12
_COMMAND_PREVIEW_CHARS: Final[int] = 80
_TIMEOUT_DURATION_TOLERANCE_MS: Final[int] = 250
_LEADER_LINE_PATTERN: Final[re.Pattern[bytes]] = re.compile(rb"__LP_LEADER__ (\d+) (\d+)")
_LEADER_LINE_MAX_BYTES: Final[int] = 128
_LEADER_SCRIPT: Final[str] = 'IFS=" "; set -f; read -r stat < /proc/$$/stat; emit() { shift 19; printf "__LP_LEADER__ %s %s\\n" "$$" "$1"; }; emit ${stat##*) }; exec "$@"'
_LAUNCH_SCRIPT: Final[str] = f'exec 3>&2 2>/dev/null; group_tag="$1"; shift; /usr/bin/setpriv --groups "0,$group_tag" /usr/bin/setsid /bin/sh -c {shlex.quote(_LEADER_SCRIPT)} sh "$@" 2>&3 3>&- & wait "$!"; exit "$?"'
_VARIABLE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def validate_environment(environment: dict[str, str]) -> None:
    for name, value in environment.items():
        if _VARIABLE_NAME_PATTERN.fullmatch(name) is None:
            raise InvalidArgumentError(f"The env name {name!r} is invalid. Use letters, digits and underscores, and do not start with a digit.")

        if "\x00" in value:
            raise InvalidArgumentError(f"The env value of {name} contains a NUL character. Remove it.")


class _LeaderLineReader:
    def __init__(self, stdout_capture: OutputCapture) -> None:
        self._stdout_capture = stdout_capture
        self._pending = bytearray()
        self._is_resolved = False
        self.identity: tuple[int, str] | None = None

    def append(self, data: bytes) -> None:
        if self._is_resolved:
            self._stdout_capture.append(data)
            return

        self._pending += data
        line_end = self._pending.find(b"\n")
        if line_end < 0:
            if len(self._pending) > _LEADER_LINE_MAX_BYTES:
                self.finish()

            return

        leader_match = _LEADER_LINE_PATTERN.fullmatch(bytes(self._pending[:line_end]))
        if leader_match is not None:
            self.identity = int(leader_match.group(1)), leader_match.group(2).decode()
            del self._pending[: line_end + 1]

        self.finish()

    def finish(self) -> None:
        self._is_resolved = True
        if self._pending:
            self._stdout_capture.append(bytes(self._pending))
            self._pending.clear()


class SandboxClient:
    def __init__(self, container_name: str, default_output_char_limit: int = OUTPUT_CHAR_LIMIT_DEFAULT) -> None:
        self._container_name = container_name
        self._default_output_char_limit = default_output_char_limit
        self._docker: aiodocker.Docker | None = None
        self._kill_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        try:
            container = await self._container()
        except SandboxUnavailableError as error:
            logger.warning(f"SandboxClient could not reach the sandbox at startup, will retry on demand: {error}")
            return

        logger.info(f"SandboxClient connected container={self._container_name} id={container.id[:_CONTAINER_ID_PREVIEW_CHARS]}")

    async def close(self) -> None:
        await asyncio.gather(*self._kill_tasks, return_exceptions=True)
        await self._reset_docker()

    async def generation(self) -> SandboxGeneration:
        container = await self._container()
        return self._generation(container)

    async def exec_once(self, command: str, workdir: str, timeout: int, environment: dict[str, str] | None = None, expected_generation: SandboxGeneration | None = None, *, output_char_limit: int | None = None, should_kill_leftovers: bool = True) -> ShellResult:
        workdir = resolve_command_cwd(workdir)
        environment = environment or {}
        validate_environment(environment)
        container = await self._container(expected_generation)
        command_preview = command[:_COMMAND_PREVIEW_CHARS]
        backstop_timeout = timeout + EXEC_TIMEOUT_KILL_GRACE_SECONDS + EXEC_TIMEOUT_BACKSTOP_SECONDS

        output_char_limit = self._default_output_char_limit if output_char_limit is None else output_char_limit
        stdout_capture = OutputCapture(output_char_limit)
        stderr_capture = OutputCapture(output_char_limit)
        leader_reader = _LeaderLineReader(stdout_capture)
        exec_marker = uuid4().hex
        group_tag = EXEC_GROUP_TAG_MIN + randbelow(EXEC_GROUP_TAG_COUNT)
        is_backstop_reached = False

        running_loop = asyncio.get_running_loop()
        started_at = running_loop.time()

        try:
            exec_instance = await container.exec(
                cmd=["/bin/sh", "-c", _LAUNCH_SCRIPT, "sh", str(group_tag), "/usr/bin/timeout", "-k", str(EXEC_TIMEOUT_KILL_GRACE_SECONDS), str(timeout), "/bin/bash", "-lc", command],
                stdout=True,
                stderr=True,
                tty=False,
                workdir=workdir,
                environment={**environment, MARKER_VARIABLE: exec_marker},
            )

            try:
                async with asyncio.timeout(backstop_timeout):
                    await self._collect_output(exec_instance, leader_reader.append, stderr_capture.append)
            except TimeoutError:
                is_backstop_reached = True
                logger.warning(f"Sandbox exec_once backstop fired timeout={timeout} command={command_preview!r}")

            leader_reader.finish()
            exit_code, has_started = await self._read_exit_state(exec_instance)
        except asyncio.CancelledError:
            logger.info(f"Sandbox exec_once cancelled, killing its processes leader={leader_reader.identity} command={command_preview!r}")
            await self._kill_detached(container, leader_reader.identity, exec_marker, group_tag)
            raise
        except (ClientError, OSError) as connection_error:
            logger.warning(f"Sandbox exec_once lost its connection workdir={workdir} command={command_preview!r}: {connection_error}")
            await self._reset_docker()
            raise SandboxUnavailableError(self._container_name, _CONNECTION_FAILURE_REASON) from connection_error
        except DockerError as docker_error:
            logger.warning(f"Sandbox exec_once rejected workdir={workdir} command={command_preview!r}: {docker_error}")
            raise self._classify_docker_error(docker_error) from docker_error

        if not has_started:
            failure_output = f"{stdout_capture.render()[0]}{stderr_capture.render()[0]}"
            logger.warning(f"Sandbox exec_once could not start workdir={workdir} command={command_preview!r}: {failure_output.strip()[:ERROR_PREVIEW_CHARS]!r}")
            raise SandboxExecError(self._describe_start_failure(workdir))

        duration_ms = int((running_loop.time() - started_at) * 1000)

        is_timed_out = is_backstop_reached or self._is_timeout_exit(exit_code, duration_ms, timeout)
        if is_timed_out and not is_backstop_reached:
            logger.warning(f"Sandbox exec_once timed out timeout={timeout} exit_code={exit_code} command={command_preview!r}")

        if is_timed_out or should_kill_leftovers:
            await self._kill_detached(container, leader_reader.identity, exec_marker, group_tag)

        stdout_text, is_stdout_truncated = stdout_capture.render()
        stderr_text, is_stderr_truncated = stderr_capture.render()

        return ShellResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            truncated=is_stdout_truncated or is_stderr_truncated,
            duration_ms=duration_ms,
            timed_out=is_timed_out,
        )

    async def _container(self, expected_generation: SandboxGeneration | None = None) -> Any:
        last_reason = "unknown error"

        for attempt in range(1, SANDBOX_CONNECT_ATTEMPTS + 1):
            try:
                docker = self._ensure_docker()
                container = await docker.containers.get(self._container_name)

                if expected_generation is not None and self._generation(container) != expected_generation:
                    raise SandboxRestartedError

                return container
            except (ClientError, OSError) as connection_error:
                last_reason = _CONNECTION_FAILURE_REASON
                logger.warning(f"Sandbox connection attempt {attempt}/{SANDBOX_CONNECT_ATTEMPTS} failed container={self._container_name}: {connection_error}")
                await self._reset_docker()
            except DockerError as docker_error:
                last_reason = self._describe_docker_error(docker_error)
                logger.warning(f"Sandbox lookup attempt {attempt}/{SANDBOX_CONNECT_ATTEMPTS} failed container={self._container_name}: {docker_error}")

            if attempt < SANDBOX_CONNECT_ATTEMPTS:
                await asyncio.sleep(SANDBOX_RECONNECT_DELAY_SECONDS)

        raise SandboxUnavailableError(self._container_name, last_reason)

    def _generation(self, container: Any) -> SandboxGeneration:
        state = container["State"]
        if not state["Running"] or state.get("Restarting", False):
            raise SandboxUnavailableError(self._container_name, "container is not running")

        return SandboxGeneration(container["Id"], state["StartedAt"])

    def _ensure_docker(self) -> aiodocker.Docker:
        if self._docker is None:
            self._docker = aiodocker.Docker()

        return self._docker

    async def _reset_docker(self) -> None:
        docker, self._docker = self._docker, None
        if docker is None:
            return

        try:
            await docker.close()
        except Exception as error:
            logger.debug(f"Error closing docker client during reset: {error}")

    def _classify_docker_error(self, docker_error: DockerError) -> SandboxError:
        reason = self._describe_docker_error(docker_error)
        if docker_error.status in DOCKER_CONTAINER_GONE_STATUSES or docker_error.status == DOCKER_CLIENT_CONNECTION_ERROR_STATUS:
            return SandboxUnavailableError(self._container_name, reason)

        return SandboxExecError(reason)

    @staticmethod
    def _describe_docker_error(docker_error: DockerError) -> str:
        if docker_error.status == DOCKER_CLIENT_CONNECTION_ERROR_STATUS:
            return _CONNECTION_FAILURE_REASON

        if docker_error.status in DOCKER_CONTAINER_GONE_STATUSES:
            return _CONTAINER_GONE_REASON

        return _DOCKER_API_FAILURE_REASON

    async def _kill_detached(self, container: Any, leader_identity: tuple[int, str] | None, exec_marker: str, group_tag: int) -> None:
        leader_pid, start_ticks = leader_identity or (0, "0")
        kill_task = asyncio.create_task(self._kill_process_group(container, leader_pid, start_ticks, exec_marker, group_tag))
        self._kill_tasks.add(kill_task)
        kill_task.add_done_callback(self._kill_tasks.discard)
        await asyncio.shield(kill_task)

    async def _kill_process_group(self, container: Any, leader_pid: int, start_ticks: str, exec_marker: str, group_tag: int) -> None:
        output_capture = OutputCapture(ERROR_PREVIEW_CHARS)

        try:
            exec_instance = await container.exec(cmd=[SANDBOX_PYTHON_PATH, "-c", EXEC_KILL_SCRIPT, str(leader_pid), start_ticks, exec_marker, str(group_tag)], stdout=True, stderr=True, tty=False)
            async with asyncio.timeout(EXEC_CANCEL_KILL_TIMEOUT_SECONDS):
                await self._collect_output(exec_instance, output_capture.append, output_capture.append)

            exit_code, _ = await self._read_exit_state(exec_instance)
        except (ClientError, DockerError, OSError, TimeoutError) as connection_error:
            logger.warning(f"Failed to kill exec processes leader={leader_pid}: {connection_error!r}")
            return
        except Exception as error:
            logger.exception(f"Unexpected error while killing exec processes leader={leader_pid}: {error!r}")
            return

        if exit_code != 0:
            logger.warning(f"Failed to kill exec processes leader={leader_pid} exit_code={exit_code} output={output_capture.render()[0]!r}")

    @staticmethod
    def _describe_start_failure(workdir: str) -> str:
        return f"nothing could be started in the working directory {workdir}. Check that it exists and is accessible (details are in the server log)"

    @staticmethod
    async def _collect_output(exec_instance: Any, append_stdout: Callable[[bytes], None], append_stderr: Callable[[bytes], None]) -> None:
        async with exec_instance.start(detach=False) as stream:
            while (message := await stream.read_out()) is not None:
                if message.stream == _STDOUT_STREAM:
                    append_stdout(message.data)
                else:
                    append_stderr(message.data)

    @staticmethod
    def _is_timeout_exit(exit_code: int | None, duration_ms: int, timeout: int) -> bool:
        return exit_code in (EXEC_TIMEOUT_EXIT_CODE, EXEC_KILL_EXIT_CODE) and duration_ms >= timeout * 1000 - _TIMEOUT_DURATION_TOLERANCE_MS

    @staticmethod
    async def _read_exit_state(exec_instance: Any) -> tuple[int | None, bool]:
        inspection = await exec_instance.inspect()
        raw_exit_code = inspection.get("ExitCode")
        exit_code = int(raw_exit_code) if raw_exit_code is not None else None
        has_started = bool(inspection.get("Pid")) or inspection.get("Running", False)
        return exit_code, has_started
