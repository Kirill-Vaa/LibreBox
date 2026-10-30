import argparse
import asyncio
import json
import logging
import os
import re
import signal
from contextlib import suppress
from itertools import batched
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Final, Literal, TypedDict, cast


type ImageProfile = Literal["core", "standard", "full"]


class InventoryCommand(TypedDict):
    name: str
    path: str
    version: str | None
    is_security: bool


logger: Final[logging.Logger] = logging.getLogger("inventory")

_INVENTORY_DIRECTORY: Final[Path] = Path("/usr/local/share/libre-box")
_INVENTORY_FILE_NAME: Final[str] = "inventory.json"
_SECURITY_COMMANDS_DIRECTORY_NAME: Final[str] = "security-commands.d"
_OPTIONAL_INSTALLS_DIRECTORY_NAME: Final[str] = "optional-installs.d"
_OPTIONAL_INSTALLS_FILE_NAME: Final[str] = "optional-installs.jsonl"
_COMMAND_RESOLVE_CHUNK_SIZE: Final[int] = 2000
_COMMAND_RESOLVE_SCRIPT: Final[str] = 'for name do path="$(command -v -- "${name}")" || continue; printf "%s\\0%s\\0" "${name}" "${path}"; done'
_PROBE_CONCURRENCY: Final[int] = 8
_PROBE_TIMEOUT_SECONDS: Final[float] = 15.0
_PROBE_READ_BYTES: Final[int] = 4096
_PROBE_OUTPUT_MAX_BYTES: Final[int] = 8192
_PROBE_ENVIRONMENT: Final[dict[str, str]] = {
    "CHECKPOINT_DISABLE": "1",
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONWARNINGS": "ignore",
    "SOPS_DISABLE_VERSION_CHECK": "1",
    "TERM": "dumb",
}
_VERSION_MAX_CHARS: Final[int] = 256
_ANSI_PATTERN: Final[re.Pattern[str]] = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"v?\d+\.\d+")
_DEFAULT_PROBE_ARGUMENTS: Final[tuple[str, ...]] = ("--version",)
_DEFAULT_PROBE_COMMANDS: Final[tuple[str, ...]] = (
    "age", "age-keygen", "ansible", "ansible-lint", "apktool", "aria2c", "arp-scan", "aws",
    "bash", "bat", "batcat", "bettercap", "btop", "buildah", "bun",
    "cargo", "cat", "certipy", "cewl", "checkov", "chisel", "chrome-no-sandbox", "cmake", "corepack", "crunch", "csvcut", "csvformat", "csvgrep", "csvjoin", "csvlook", "csvsql", "csvstat", "ctags", "curl",
    "d2", "delta", "deno", "direnv", "dirsearch", "docker", "dotnet", "duf", "dust",
    "enum4linux-ng", "eslint", "ettercap", "evil-winrm", "eza",
    "fcrackzip", "fd", "fdfind", "feroxbuster", "file", "files-to-prompt", "fish", "fnm", "fping", "frida", "frida-ps", "fzf",
    "g++", "gau", "gcc", "gdb", "git", "git-lfs", "gmake", "gobuster", "google-chrome", "gpg", "grep", "gs",
    "hashcat", "hashid", "hping3", "htop", "http", "hydra", "hyperfine",
    "img2pdf", "impacket-secretsdump", "impacket-smbclient", "inkscape", "ipython",
    "jadx", "jq", "julia", "jupyter", "jwt",
    "latex", "latexmk", "libreoffice", "ligolo-agent", "llm", "lsassy", "ltrace", "luarocks",
    "maigret", "make", "mariadb", "marp", "masscan", "mmdc", "mongodump", "mongoexport", "mongoimport", "mongorestore", "mongosh", "msfconsole", "mtr", "mvn", "mysql",
    "nano", "ncat", "ncdu", "ncrack", "netexec", "nft", "nmap", "node", "npm", "nvim",
    "ocrmypdf",
    "packer", "pandoc", "parallel", "patator", "pdfcrack", "pdftk", "php", "pip", "pip3", "pipx", "playwright-cli", "pnpm", "poetry", "prettier", "procs", "prowler", "psql", "pv", "pwsh", "pyenv", "python", "python3",
    "qpdf",
    "R", "rbenv", "recon-ng", "redis-cli", "repomix", "responder", "rg", "rlwrap", "rsvg-convert", "rsync", "ruby", "rustc", "rustscan", "rustup",
    "scout", "shellcheck", "sherlock", "shfmt", "skopeo", "sops", "sox", "sqlite-utils", "sqlite3", "sqlmap", "steghide", "stegseek", "strace",
    "tcpdump", "terraform", "tesseract", "tex", "theHarvester", "tldr", "tofu", "tor", "torsocks", "trivy", "ts-node", "tsc", "tshark", "ttok", "typst",
    "upx", "usql", "uv",
    "vips", "visidata", "vol",
    "wafw00f", "weasyprint", "websocat", "wfuzz", "wget", "whatweb", "whois", "wpscan",
    "xelatex", "xh", "xxd", "xz",
    "yamllint", "yarn", "yq", "yt-dlp",
    "zoxide", "zsh", "zstd",
)
_CUSTOM_PROBE_ARGUMENTS: Final[dict[str, tuple[str, ...]]] = {
    "amass": ("-version",),
    "arping": ("--help",),
    "binwalk": ("--help",),
    "cargo-binstall": ("-V",),
    "coercer": ("--help",),
    "convert": ("-version",),
    "dasel": ("version",),
    "decktape": ("version",),
    "dig": ("-v",),
    "dnsenum": ("-V",),
    "dnsx": ("-version",),
    "dot": ("-V",),
    "exiftool": ("-ver",),
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "ffuf": ("-V",),
    "foremost": ("-V",),
    "gitleaks": ("version",),
    "gm": ("version",),
    "go": ("version",),
    "gradle": ("--version", "-Dorg.gradle.welcome=never"),
    "grype": ("version",),
    "helm": ("version", "--short"),
    "httpx-pd": ("-version",),
    "identify": ("-version",),
    "ip": ("-Version",),
    "java": ("-version",),
    "javac": ("-version",),
    "john": (),
    "k9s": ("version", "--short"),
    "katana": ("-version",),
    "kubectl": ("version", "--client=true"),
    "kustomize": ("version",),
    "lua": ("-v",),
    "lua5.4": ("-v",),
    "magick": ("-version",),
    "medusa": ("-V",),
    "mutool": ("-v",),
    "naabu": ("-version",),
    "ngrep": ("-V",),
    "nikto": ("-Version",),
    "nuclei": ("-version",),
    "openssl": ("version",),
    "pdfinfo": ("-v",),
    "pdftoppm": ("-v",),
    "pdftotext": ("-v",),
    "perl": ("-v",),
    "plantuml": ("-version",),
    "pypykatz": ("version",),
    "r2": ("-v",),
    "radare2": ("-v",),
    "scalpel": ("-v",),
    "sliver-client": ("version",),
    "sliver-server": ("version",),
    "socat": ("-V",),
    "ssdeep": ("-V",),
    "ssh": ("-V",),
    "subfinder": ("-version",),
    "syft": ("version",),
    "termshark": ("--pass-thru=false", "-v"),
    "tmux": ("-V",),
    "unzip": ("-v",),
    "vault": ("version",),
    "zip": ("-v",),
}
_UNPROBED_COMMANDS: Final[tuple[str, ...]] = (
    "arjun","assetfinder",
    "bloodhound-python",
    "commix",
    "dnsrecon", "droopescan",
    "fierce",
    "ghidra",
    "hakrawler", "hexedit", "holehe", "httpx",
    "impacket-psexec", "impacket-smbexec",
    "ldapdomaindump",
    "msfvenom",
    "proxychains4",
    "searchsploit", "smbmap", "sublist3r",
    "waybackurls",
    "zsteg",
)
_NONZERO_EXIT_COMMANDS: Final[frozenset[str]] = frozenset({"dnsenum", "enum4linux-ng", "hydra", "impacket-secretsdump", "masscan", "patator", "plantuml", "theHarvester", "vol"})
_TOOLCHAIN_COMMANDS: Final[dict[str, tuple[str, ...] | None]] = {**dict.fromkeys(_DEFAULT_PROBE_COMMANDS, _DEFAULT_PROBE_ARGUMENTS), **_CUSTOM_PROBE_ARGUMENTS, **dict.fromkeys(_UNPROBED_COMMANDS)}


def list_executable_names() -> list[str]:
    names: set[str] = set()
    for directory in os.get_exec_path():
        try:
            for path in Path(directory).iterdir():
                if path.is_file() and os.access(path, os.X_OK):
                    names.add(path.name)
        except (FileNotFoundError, NotADirectoryError):
            continue

    return sorted(names)


async def resolve_command_chunk(names: tuple[str, ...]) -> dict[str, str]:
    process = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        _COMMAND_RESOLVE_SCRIPT,
        "inventory",
        *names,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        raise ValueError("Failed to resolve inventory commands with command -v")

    fields = output.decode().split("\0")
    return dict(zip(fields[:-1:2], fields[1:-1:2], strict=True))


async def discover_commands() -> dict[str, str]:
    names = await asyncio.to_thread(list_executable_names)
    commands: dict[str, str] = {}
    for name_chunk in batched(names, _COMMAND_RESOLVE_CHUNK_SIZE, strict=False):
        commands.update(await resolve_command_chunk(name_chunk))

    return {name: path for name, path in commands.items() if Path(path).is_absolute()}


def read_security_commands(directory: Path) -> set[str]:
    security_commands: set[str] = set()
    for path in sorted((directory / _SECURITY_COMMANDS_DIRECTORY_NAME).glob("*.txt")):
        security_commands.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    return security_commands


def merge_optional_installs(directory: Path) -> None:
    merged_lines: list[str] = []
    for path in sorted((directory / _OPTIONAL_INSTALLS_DIRECTORY_NAME).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue

            try:
                record: object = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid optional install record in {path}: {line}") from error

            if not isinstance(record, dict) or record.get("status") not in ("installed", "skipped"):
                raise ValueError(f"Invalid optional install record in {path}: {line}")

            merged_lines.append(json.dumps(record, ensure_ascii=False))
            if record["status"] == "skipped":
                logger.warning(f"Optional {record.get('category')} package {record.get('package')} was skipped during the build")

    output_path = directory / _OPTIONAL_INSTALLS_FILE_NAME
    output_path.write_text("".join(f"{line}\n" for line in merged_lines), encoding="utf-8")
    output_path.chmod(0o644)


def normalize_version(output: bytes) -> str | None:
    text = _ANSI_PATTERN.sub("", output.decode(errors="replace"))
    lines = [" ".join("".join(character for character in line if character.isprintable()).split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    version_line = next((line for line in lines if _VERSION_PATTERN.search(line)), None)
    if version_line is None:
        return next((line for line in lines if any(character.isdigit() for character in line)), lines[0])[:_VERSION_MAX_CHARS]

    version_match = _VERSION_PATTERN.search(version_line)
    if version_match is not None and not any(character.isalnum() for character in version_line[: version_match.start()]):
        version_line = version_line[version_match.start() :]

    return version_line[:_VERSION_MAX_CHARS]


async def probe_version(path: str, arguments: tuple[str, ...], environment: dict[str, str], working_directory: str, is_exit_code_ignored: bool = False) -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=environment,
            cwd=working_directory,
            start_new_session=True,
            limit=_PROBE_OUTPUT_MAX_BYTES,
        )
    except PermissionError as permission_error:
        logger.warning(f"Cannot probe the version of {path}, it is not executable by the build user: {permission_error}")
        return None
    except OSError:
        return None

    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            if process.stdout is None:
                return None

            output = bytearray()
            while chunk := await process.stdout.read(_PROBE_READ_BYTES):
                if len(output) + len(chunk) > _PROBE_OUTPUT_MAX_BYTES:
                    return None

                output.extend(chunk)

            await process.wait()
            return normalize_version(bytes(output)) if process.returncode == 0 or is_exit_code_ignored else None
    except TimeoutError:
        return None
    finally:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)

        await process.communicate()


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False) as temporary_file:
        temporary_file.write(json.dumps(content, ensure_ascii=False, separators=(",", ":")))
        temporary_path = Path(temporary_file.name)

    temporary_path.chmod(0o644)
    temporary_path.replace(path)


async def write_inventory(profile: ImageProfile, directory: Path) -> None:
    commands = await discover_commands()
    security_commands = read_security_commands(directory)
    merge_optional_installs(directory)
    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

    with TemporaryDirectory(prefix="libre-box-inventory-") as working_directory:
        environment = {**os.environ, **_PROBE_ENVIRONMENT, "HOME": working_directory, "XDG_CACHE_HOME": f"{working_directory}/cache"}
        environment.pop("DISPLAY", None)

        async def inspect_command(name: str, path: str) -> InventoryCommand:
            version = None
            if (arguments := _TOOLCHAIN_COMMANDS.get(name)) is not None:
                async with semaphore:
                    version = await probe_version(path, arguments, environment, working_directory, is_exit_code_ignored=name in _NONZERO_EXIT_COMMANDS)

            return {"name": name, "path": path, "version": version, "is_security": name in security_commands}

        inventory_commands = await asyncio.gather(*(inspect_command(name, path) for name, path in commands.items()))

    toolchain_commands = [name for name in commands if name in _TOOLCHAIN_COMMANDS]
    write_json(directory / _INVENTORY_FILE_NAME, {"profile": profile, "commands": inventory_commands, "toolchain_commands": toolchain_commands})


async def main() -> None:
    parser = argparse.ArgumentParser(description="Record the sandbox image tool inventory")
    parser.add_argument("--profile", choices=("core", "standard", "full"), required=True)
    parser.add_argument("--directory", type=Path, default=_INVENTORY_DIRECTORY)
    arguments = parser.parse_args()
    logging.basicConfig(format="%(levelname)s: %(message)s")
    await write_inventory(cast(ImageProfile, arguments.profile), arguments.directory)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"Failed to generate sandbox inventory: {error}") from error
