import asyncio
import base64
import json
import re
import shlex
from dataclasses import dataclass
from secrets import choice
from string import ascii_lowercase, digits
from typing import Any, Final, Literal

from config.constants import ERROR_PREVIEW_CHARS, OUTPUT_CHAR_LIMIT_DEFAULT, SANDBOX_PYTHON_PATH
from domain.exceptions import ProcessNotFoundError, SandboxError, SandboxRestartedError
from domain.generation import SandboxGeneration
from domain.models import BackgroundProcessInfo, BackgroundTailResult, BackgroundWaitResult, ShellResult, SignalName
from infrastructure.docker.sandbox_client import SandboxClient, validate_environment
from sandbox_scripts import IDENTITY_SCRIPT, METADATA_SCAN_SCRIPT, METADATA_WRITE_SCRIPT, PROBE_SCRIPT, RECORD_EXIT_SCRIPT, SIGNAL_SCRIPT, TAIL_CHUNK_SCRIPT, TAIL_LINES_SCRIPT
from sandbox_scripts.identity import IDENTITY_FAILED_EXIT_CODE, IDENTITY_MARKER
from sandbox_scripts.signal_group import GONE_EXIT_CODE, MEMBERS_ONLY_EXIT_CODE
from sandbox_scripts.tail_output import BYTE_COUNT_MARKER
from services.background_constants import BACKGROUND_COMMAND_PREVIEW_CHARS, BACKGROUND_CONTROL_TIMEOUT_SECONDS, BACKGROUND_GATE_TIMEOUT_EXIT_CODE, BACKGROUND_LAUNCH_TIMEOUT_SECONDS, BACKGROUND_LOG_LIMIT_FAILED_EXIT_CODE, BACKGROUND_LOG_MAX_BYTES, BACKGROUND_MAX_TRACKED_PROCESSES, BACKGROUND_METADATA_MAX_BYTES, BACKGROUND_METADATA_SCAN_MAX_CHARS, BACKGROUND_METADATA_SCAN_PAGE_CHARS, BACKGROUND_METADATA_SCAN_PAGE_SECONDS, BACKGROUND_METADATA_WAIT_INTERVAL_SECONDS, BACKGROUND_METADATA_WAIT_SECONDS, BACKGROUND_METADATA_WRITE_CHUNK_CHARS, BACKGROUND_POLL_INTERVAL_SECONDS, BACKGROUND_PROBE_CONCURRENCY, BACKGROUND_PROCESS_ID_LENGTH, BACKGROUND_RESTORE_RETRY_SECONDS, BACKGROUND_TAIL_DEFAULT_LINES
from utils.logger import logger


SignalDelivery = SignalName | Literal["PROBE"]

_PROCESS_ID_PATTERN: Final[re.Pattern[str]] = re.compile(rf"[0-9a-z]{{{BACKGROUND_PROCESS_ID_LENGTH}}}")
_LOG_DIRECTORY_FAILED_EXIT_CODE: Final[int] = 73
_SIGNAL_EXIT_CODES: Final[dict[str, int]] = {"HUP": 129, "INT": 130, "KILL": 137, "QUIT": 131, "TERM": 143, "USR1": 138, "USR2": 140}
_COMMAND_LAUNCHER: Final[str] = "/usr/bin/env"
_PYTHON: Final[str] = f"{SANDBOX_PYTHON_PATH} -I"
_UNTRAPPABLE_SIGNALS: Final[frozenset[str]] = frozenset({"KILL"})
_SIGNAL_TRAP_PREFIX: Final[str] = " ".join(f"trap 'status=$?; [[ $BASH_COMMAND == {_COMMAND_LAUNCHER}\\ --\\ * ]] && exit $status; exit {_SIGNAL_EXIT_CODES[signal_name]}' {signal_name};" for signal_name in sorted(_SIGNAL_EXIT_CODES.keys() - _UNTRAPPABLE_SIGNALS))
_JOB_SCRIPT: Final[str] = (
    "trap 'echo $? > \"$3\"' EXIT; "
    f"{_SIGNAL_TRAP_PREFIX} "
    f"gate_deadline=$((SECONDS + {BACKGROUND_METADATA_WAIT_SECONDS})); "
    f'until [[ -f $4 ]]; do (( SECONDS < gate_deadline )) || {{ echo "libre-box: the launch metadata did not appear in time, so the command was not started." >&2; exit {BACKGROUND_GATE_TIMEOUT_EXIT_CODE}; }}; sleep {BACKGROUND_METADATA_WAIT_INTERVAL_SECONDS}; done; '
    "[[ -n $2 ]] && export BASH_ENV=${2#x}; "
    "export SHLVL=$((SHLVL - 1)); "
    f'ulimit -f {BACKGROUND_LOG_MAX_BYTES // 1024} || {{ echo "libre-box: the file-size limit could not be set, so the command was not started." >&2; exit {BACKGROUND_LOG_LIMIT_FAILED_EXIT_CODE}; }}; '
    f'{_COMMAND_LAUNCHER} -- "${{@:5}}" "$BASH" -lc -- "$1" bash'
)
_TERMINATING_SIGNALS: Final[frozenset[str]] = frozenset({"INT", "KILL", "QUIT", "TERM"})
_KILL_SETTLE_TIMEOUT_SECONDS: Final[int] = 5


@dataclass
class TrackedBackgroundProcess:
    info: BackgroundProcessInfo
    generation: SandboxGeneration
    start_ticks: str


class BackgroundService:
    def __init__(self, sandbox_client: SandboxClient, log_dir: str, output_char_limit: int = OUTPUT_CHAR_LIMIT_DEFAULT) -> None:
        self._sandbox_client = sandbox_client
        self._log_dir = log_dir
        self._output_char_limit = output_char_limit
        self._generation: SandboxGeneration | None = None
        self._is_restore_complete = False
        self._next_restore_attempt = 0.0
        self._processes: dict[str, TrackedBackgroundProcess] = {}
        self._registry_lock = asyncio.Lock()
        self._probe_semaphore = asyncio.Semaphore(BACKGROUND_PROBE_CONCURRENCY)

    async def start(self, command: str, cwd: str, environment: dict[str, str]) -> BackgroundProcessInfo:
        generation = await self._sync_generation()
        validate_environment(environment)
        process_id = "".join(choice(digits + ascii_lowercase) for _ in range(BACKGROUND_PROCESS_ID_LENGTH))
        log_path = shlex.quote(self._artifact_path(process_id, "log"))
        exit_path = shlex.quote(self._artifact_path(process_id, "exit"))
        metadata_path = shlex.quote(self._artifact_path(process_id, "json"))
        bash_env = environment.get("BASH_ENV")
        bash_env_argument = "" if bash_env is None else f"x{bash_env}"
        command_environment = " ".join(shlex.quote(f"{name}={value}") for name, value in environment.items() if name != "BASH_ENV")

        launch_command = (
            f"/bin/mkdir -p {shlex.quote(self._log_dir)} || exit {_LOG_DIRECTORY_FAILED_EXIT_CODE}; "
            f"/usr/bin/setsid /usr/bin/env -u BASH_ENV --default-signal=INT,QUIT /bin/bash -c {shlex.quote(_JOB_SCRIPT)} bash "
            f"{shlex.quote(command)} {shlex.quote(bash_env_argument)} {exit_path} {metadata_path} {command_environment} > {log_path} 2>&1 < /dev/null & "
            f'pid=$!; {_PYTHON} -c {shlex.quote(IDENTITY_SCRIPT)} "$pid"'
        )
        launch_result = await self._sandbox_client.exec_once(launch_command, cwd, BACKGROUND_LAUNCH_TIMEOUT_SECONDS, expected_generation=generation, should_kill_leftovers=False)

        try:
            start_ticks, pid_text = self._parse_launch_identity(launch_result.stdout)
            pid = int(pid_text)
            if not start_ticks.isdigit() or launch_result.exit_code != 0:
                raise ValueError("Invalid process identity")
        except ValueError as error:
            logger.warning(f"Background launch failed process_id={process_id} exit_code={launch_result.exit_code} timed_out={launch_result.timed_out} output={(launch_result.stdout + launch_result.stderr)[:ERROR_PREVIEW_CHARS]!r}")
            raise SandboxError(f"Could not start the background process: {self._describe_launch_failure(launch_result)}.") from error

        info = BackgroundProcessInfo(process_id=process_id, pid=pid, command=self._preview_command(command), status="running")
        metadata = json.dumps(
            {
                "info": info.model_dump(mode="json"),
                "container_id": generation.container_id,
                "started_at": generation.started_at,
                "start_ticks": start_ticks,
            }
        )
        try:
            write_error = await self._write_metadata(metadata_path, metadata, generation)
        except (SandboxError, asyncio.CancelledError):
            await asyncio.shield(self._abort_launch(process_id, pid, start_ticks, generation))
            raise

        if write_error is not None:
            await self._abort_launch(process_id, pid, start_ticks, generation)
            raise SandboxError(f"Could not record the background process metadata, so the process was stopped instead of being left untracked: {write_error}.")

        async with self._registry_lock:
            if self._generation != generation:
                info.status = "sandbox_restarted"

            self._processes[process_id] = TrackedBackgroundProcess(info, generation, start_ticks)
            self._evict_finished_processes()

        logger.info(f"Background process started process_id={process_id} pid={pid}")
        return info

    def _evict_finished_processes(self) -> None:
        surplus = len(self._processes) - BACKGROUND_MAX_TRACKED_PROCESSES
        if surplus <= 0:
            return

        for process_id, tracked in list(self._processes.items()):
            if surplus == 0:
                break

            if tracked.info.status == "running":
                continue

            del self._processes[process_id]
            surplus -= 1
            logger.info(f"Evicted finished background process from the registry process_id={process_id} status={tracked.info.status}")

        if surplus > 0:
            logger.warning(f"Background registry holds {len(self._processes)} processes, above the {BACKGROUND_MAX_TRACKED_PROCESSES} limit, because none of the surplus entries have finished")

    async def _abort_launch(self, process_id: str, pid: int, start_ticks: str, generation: SandboxGeneration) -> None:
        try:
            await self._run_control(self._build_signal_command(pid, start_ticks, "TERM"), generation)
        except SandboxError as error:
            logger.warning(f"Failed to stop background process after a failed launch process_id={process_id} pid={pid}: {error}")

    async def _write_metadata(self, metadata_path: str, metadata: str, generation: SandboxGeneration) -> str | None:
        encoded = base64.b64encode(metadata.encode()).decode("ascii")
        chunks = [encoded[index : index + BACKGROUND_METADATA_WRITE_CHUNK_CHARS] for index in range(0, len(encoded), BACKGROUND_METADATA_WRITE_CHUNK_CHARS)]
        try:
            for index, chunk in enumerate(chunks):
                mode = "only" if len(chunks) == 1 else "first" if index == 0 else "last" if index == len(chunks) - 1 else "middle"
                write_command = f"{_PYTHON} -c {shlex.quote(METADATA_WRITE_SCRIPT)} {metadata_path} {mode} {shlex.quote(chunk)}"
                write_result = await self._run_control(write_command, generation)
                if write_result.timed_out or write_result.truncated or write_result.exit_code != 0:
                    await self._discard_metadata_staging(metadata_path, generation)
                    return self._failure_reason(write_result)
        except asyncio.CancelledError:
            await asyncio.shield(self._discard_metadata_staging(metadata_path, generation))
            raise
        except SandboxError:
            await self._discard_metadata_staging(metadata_path, generation)
            raise

        return None

    async def _discard_metadata_staging(self, metadata_path: str, generation: SandboxGeneration) -> None:
        try:
            await self._run_control(f"/bin/rm -f -- {metadata_path}.b64 {metadata_path}.new", generation)
        except SandboxError as error:
            logger.warning(f"Failed to remove background metadata staging files path={metadata_path}: {error}")

    async def status(self, process_id: str) -> BackgroundProcessInfo:
        generation = await self._sync_generation()
        return await self._refresh_status(process_id, generation)

    async def _refresh_status(self, process_id: str, generation: SandboxGeneration) -> BackgroundProcessInfo:
        tracked = self._require(process_id)
        info = tracked.info

        if tracked.generation != generation or info.status == "sandbox_restarted":
            info.status = "sandbox_restarted"
            return info

        if info.status == "exited":
            return info

        exit_path = shlex.quote(self._artifact_path(process_id, "exit"))
        probe_command = f"{_PYTHON} -c {shlex.quote(PROBE_SCRIPT)} {info.pid} {shlex.quote(tracked.start_ticks)} {exit_path}"
        async with self._probe_semaphore:
            result = await self._run_control(probe_command, generation)

        self._require_success(result, f"read the state of background process '{process_id}'")
        try:
            probe = json.loads(result.stdout)
            exit_code = None if probe["exit_code"] is None else int(probe["exit_code"])
            is_running = bool(probe["is_running"])
        except (ValueError, KeyError, TypeError) as error:
            raise SandboxError(f"Could not read the state of background process '{process_id}'. The sandbox returned unexpected output: {result.stdout[:ERROR_PREVIEW_CHARS]!r}.") from error

        if exit_code is not None:
            info.status = "exited"
            info.exit_code = exit_code
        elif is_running:
            info.status = "running"
        else:
            info.status = "lost"
            info.exit_code = None

        return info

    async def tail(self, process_id: str, lines: int, offset_bytes: int | None) -> BackgroundTailResult:
        generation = await self._sync_generation()
        tracked = self._require(process_id)
        if tracked.generation.container_id != generation.container_id:
            raise SandboxError(f"The log of background process '{process_id}' was lost when the sandbox was recreated. Start the command again.")

        log_path = shlex.quote(self._artifact_path(process_id, "log"))
        header_reserve = self._tail_header_reserve_chars()
        tail_char_limit = max(self._output_char_limit, header_reserve + 1)
        chunk_bytes = tail_char_limit - header_reserve
        if offset_bytes is None:
            tail_command = f"{_PYTHON} -c {shlex.quote(TAIL_LINES_SCRIPT)} {log_path} {lines} {chunk_bytes}"
        else:
            tail_command = f"{_PYTHON} -c {shlex.quote(TAIL_CHUNK_SCRIPT)} {log_path} {offset_bytes} {chunk_bytes}"

        result = await self._run_control(tail_command, generation, output_char_limit=tail_char_limit)
        self._require_success(result, f"read the log of background process '{process_id}'")
        total_bytes, next_offset, is_truncated, content = self._parse_tail_output(result.stdout)
        return BackgroundTailResult(process_id=process_id, content=content, total_bytes=total_bytes, next_offset=next_offset, truncated=is_truncated)

    async def stop(self, process_id: str, signal: SignalName, timeout: int) -> BackgroundProcessInfo:
        info = await self.status(process_id)
        if info.status == "sandbox_restarted":
            return info

        running_loop = asyncio.get_running_loop()
        deadline = running_loop.time() + timeout
        was_running = info.status == "running"
        delivery = await self._signal_process(process_id, signal)
        if delivery == "gone" or signal not in _TERMINATING_SIGNALS:
            return await self.status(process_id)

        if not was_running:
            await self._wait_for_group_exit(process_id, deadline)
            return await self.status(process_id)

        info = await self._poll_until_finished(process_id, max(deadline - running_loop.time(), 0))
        if info.status != "running":
            await self._wait_for_group_exit(process_id, deadline)
            return await self._finish_stop(process_id, signal)

        if await self._signal_process(process_id, "KILL") == "gone":
            return await self.status(process_id)

        await self._poll_until_finished(process_id, _KILL_SETTLE_TIMEOUT_SECONDS)
        await self._wait_for_group_exit(process_id, running_loop.time() + _KILL_SETTLE_TIMEOUT_SECONDS)
        return await self._finish_stop(process_id, "KILL")

    async def _wait_for_group_exit(self, process_id: str, deadline: float) -> None:
        running_loop = asyncio.get_running_loop()
        while await self._signal_process(process_id, "PROBE") != "gone":
            if running_loop.time() >= deadline:
                logger.info(f"Background process group still has members after its leader exited, sending KILL process_id={process_id}")
                await self._signal_process(process_id, "KILL")
                return

            await asyncio.sleep(BACKGROUND_POLL_INTERVAL_SECONDS)

    async def wait(self, process_id: str, timeout: int) -> BackgroundWaitResult:
        info = await self._poll_until_finished(process_id, timeout)
        return await self._build_wait_result(info)

    async def list_processes(self) -> list[BackgroundProcessInfo]:
        generation = await self._sync_generation()
        statuses = await asyncio.gather(*(self._status_or_last_known(process_id, generation) for process_id in list(self._processes)))
        self._evict_finished_processes()
        return [info for info in statuses if info is not None]

    async def _status_or_last_known(self, process_id: str, generation: SandboxGeneration) -> BackgroundProcessInfo | None:
        try:
            return await self._refresh_status(process_id, generation)
        except ProcessNotFoundError:
            return None
        except SandboxRestartedError:
            tracked = self._processes.get(process_id)
            if tracked is None:
                return None

            tracked.info.status = "sandbox_restarted"
            return tracked.info
        except SandboxError as error:
            logger.warning(f"Failed to refresh background process status process_id={process_id}, reporting last known state: {error}")
            tracked = self._processes.get(process_id)
            return None if tracked is None else tracked.info

    async def _sync_generation(self) -> SandboxGeneration:
        async with self._registry_lock:
            generation = await self._sandbox_client.generation()
            running_loop = asyncio.get_running_loop()
            if generation == self._generation and (self._is_restore_complete or running_loop.time() < self._next_restore_attempt):
                return generation

            restored: dict[str, TrackedBackgroundProcess] = {}
            is_restore_complete = True
            try:
                await self._restore_processes(generation, restored)
            except SandboxError as error:
                is_restore_complete = False
                logger.warning(f"Failed to restore background processes from {self._log_dir}, continuing with {len(restored)} recovered and retrying in {BACKGROUND_RESTORE_RETRY_SECONDS} s: {error}")

            for tracked in self._processes.values():
                if tracked.generation != generation:
                    tracked.info.status = "sandbox_restarted"

            for process_id, restored_process in restored.items():
                self._processes.setdefault(process_id, restored_process)

            self._evict_finished_processes()
            self._generation = generation
            self._is_restore_complete = is_restore_complete
            self._next_restore_attempt = running_loop.time() + BACKGROUND_RESTORE_RETRY_SECONDS
            return generation

    async def _restore_processes(self, generation: SandboxGeneration, restored: dict[str, TrackedBackgroundProcess]) -> None:
        cursor = ""
        while True:
            records, skipped, next_cursor = await self._scan_metadata_page(generation, cursor)
            for reason in skipped:
                logger.warning(f"Skipped invalid background metadata in {self._log_dir}: {reason}")

            for record in records:
                if len(restored) >= BACKGROUND_MAX_TRACKED_PROCESSES:
                    logger.warning(f"Background metadata in {self._log_dir} holds more than {BACKGROUND_MAX_TRACKED_PROCESSES} processes of this sandbox, skipping the rest")
                    return

                self._restore_record(restored, record, generation)

            if next_cursor is None:
                return

            if not isinstance(next_cursor, str) or next_cursor <= cursor:
                raise SandboxError(f"Could not recover background processes: the metadata scan of {self._log_dir} did not advance past {cursor!r}")

            cursor = next_cursor

    async def _scan_metadata_page(self, generation: SandboxGeneration, cursor: str) -> tuple[list[Any], list[Any], Any]:
        scan_command = f"{_PYTHON} -c {shlex.quote(METADATA_SCAN_SCRIPT)} {shlex.quote(self._log_dir)} {shlex.quote(generation.container_id)} {shlex.quote(generation.started_at)} {BACKGROUND_PROCESS_ID_LENGTH} {BACKGROUND_METADATA_MAX_BYTES} {shlex.quote(cursor)} {BACKGROUND_METADATA_SCAN_PAGE_CHARS} {BACKGROUND_METADATA_SCAN_PAGE_SECONDS}"
        result = await self._sandbox_client.exec_once(scan_command, "/", BACKGROUND_CONTROL_TIMEOUT_SECONDS, expected_generation=generation, output_char_limit=BACKGROUND_METADATA_SCAN_MAX_CHARS, should_kill_leftovers=False)
        self._require_success(result, f"recover background processes by scanning the metadata in {self._log_dir}")
        try:
            scan = json.loads(result.stdout)
            records, skipped, next_cursor = scan["records"], scan["skipped"], scan["next_cursor"]
            if not isinstance(records, list) or not isinstance(skipped, list):
                raise TypeError("records and skipped must be lists")
        except (ValueError, KeyError, TypeError) as error:
            raise SandboxError(f"Could not recover background processes. The metadata scan returned unexpected output: {result.stdout[:ERROR_PREVIEW_CHARS]!r}") from error

        return records, skipped, next_cursor

    def _restore_record(self, restored: dict[str, TrackedBackgroundProcess], record: Any, generation: SandboxGeneration) -> None:
        try:
            process_id = record["process_id"]
            tracked = self._parse_metadata(process_id, record["metadata"])
        except (ValueError, KeyError, TypeError) as error:
            logger.warning(f"Skipped invalid background metadata record in {self._log_dir}: {error}")
            return

        if tracked.generation == generation:
            restored[process_id] = tracked

    async def _poll_until_finished(self, process_id: str, timeout: float) -> BackgroundProcessInfo:
        running_loop = asyncio.get_running_loop()
        deadline = running_loop.time() + timeout
        while running_loop.time() < deadline:
            info = await self.status(process_id)
            if info.status != "running":
                return info

            await asyncio.sleep(BACKGROUND_POLL_INTERVAL_SECONDS)

        return await self.status(process_id)

    async def _signal_process(self, process_id: str, signal: SignalDelivery) -> Literal["leader", "members", "gone"]:
        tracked = self._require(process_id)
        signal_command = self._build_signal_command(tracked.info.pid, tracked.start_ticks, signal)
        result = await self._run_control(signal_command, tracked.generation)
        if not result.timed_out:
            if result.exit_code == 0:
                return "leader"

            if result.exit_code == MEMBERS_ONLY_EXIT_CODE:
                return "members"

            if result.exit_code == GONE_EXIT_CODE:
                return "gone"

        raise SandboxError(f"Could not signal background process '{process_id}': {self._failure_reason(result)}.")

    async def _finish_stop(self, process_id: str, signal: SignalName) -> BackgroundProcessInfo:
        tracked = self._require(process_id)
        info = tracked.info
        if info.status != "lost" or signal != "KILL":
            return info

        signal_exit_code = _SIGNAL_EXIT_CODES[signal]
        exit_path = shlex.quote(self._artifact_path(process_id, "exit"))
        record_command = f"{_PYTHON} -c {shlex.quote(RECORD_EXIT_SCRIPT)} {exit_path} {signal_exit_code}"
        result = await self._run_control(record_command, tracked.generation)
        if result.exit_code != 0:
            logger.warning(f"Failed to record signal exit code process_id={process_id} signal={signal}: {result.stderr.strip()[:ERROR_PREVIEW_CHARS]}")
            return info

        info.status = "exited"
        info.exit_code = signal_exit_code
        return info

    async def _build_wait_result(self, info: BackgroundProcessInfo) -> BackgroundWaitResult:
        try:
            tail_result = await self.tail(info.process_id, BACKGROUND_TAIL_DEFAULT_LINES, None)
        except SandboxError as error:
            logger.warning(f"Failed to read the log tail after waiting, returning the result without it process_id={info.process_id}: {error}")
            return BackgroundWaitResult(process_id=info.process_id, status=info.status, exit_code=info.exit_code, tail="")

        return BackgroundWaitResult(process_id=info.process_id, status=info.status, exit_code=info.exit_code, tail=tail_result.content, truncated=tail_result.truncated)

    async def _run_control(self, command: str, generation: SandboxGeneration, workdir: str | None = None, output_char_limit: int | None = None) -> ShellResult:
        return await self._sandbox_client.exec_once(command, workdir or "/", BACKGROUND_CONTROL_TIMEOUT_SECONDS, expected_generation=generation, output_char_limit=output_char_limit, should_kill_leftovers=False)

    def _describe_launch_failure(self, result: ShellResult) -> str:
        if result.timed_out:
            return "the launch timed out"

        if result.exit_code == _LOG_DIRECTORY_FAILED_EXIT_CODE:
            return f"the log directory {self._log_dir} could not be created"

        if result.exit_code == IDENTITY_FAILED_EXIT_CODE:
            return "the process could not be identified, so it was not started"

        if result.exit_code == 0:
            return "the sandbox returned no valid process identity"

        return f"the launch command failed with exit code {result.exit_code}"

    def _artifact_path(self, process_id: str, extension: str) -> str:
        return f"{self._log_dir}/{process_id}.{extension}"

    def _require(self, process_id: str) -> TrackedBackgroundProcess:
        tracked = self._processes.get(process_id)
        if tracked is None:
            raise ProcessNotFoundError(process_id)

        return tracked

    @staticmethod
    def _failure_reason(result: ShellResult) -> str:
        if result.timed_out:
            return "the command timed out"

        if result.truncated:
            return "the output exceeded the limit"

        return result.stderr.strip()[-ERROR_PREVIEW_CHARS:] or f"exit code {result.exit_code}"

    @staticmethod
    def _require_success(result: ShellResult, operation: str) -> None:
        if result.timed_out or result.truncated or result.exit_code != 0:
            raise SandboxError(f"Could not {operation}: {BackgroundService._failure_reason(result)}.")

    @staticmethod
    def _parse_launch_identity(output: str) -> tuple[str, str]:
        identity_lines = [line.split() for line in output.splitlines() if line.startswith(f"{IDENTITY_MARKER} ")]
        if len(identity_lines) != 1 or len(identity_lines[0]) != 3:
            raise ValueError("Missing process identity line")

        return identity_lines[0][1], identity_lines[0][2]

    @staticmethod
    def _parse_metadata(process_id: str, metadata: dict[str, Any]) -> TrackedBackgroundProcess:
        info = BackgroundProcessInfo.model_validate(metadata["info"])
        start_ticks = str(metadata["start_ticks"])
        if _PROCESS_ID_PATTERN.fullmatch(process_id) is None or info.process_id != process_id or not start_ticks.isdigit() or info.pid <= 1:
            raise ValueError("Invalid process identity")

        info.command = BackgroundService._preview_command(info.command)
        info.status = "running"
        info.exit_code = None
        previous_generation = SandboxGeneration(metadata["container_id"], metadata["started_at"])
        return TrackedBackgroundProcess(info, previous_generation, start_ticks)

    @staticmethod
    def _preview_command(command: str) -> str:
        return command if len(command) <= BACKGROUND_COMMAND_PREVIEW_CHARS else f"{command[:BACKGROUND_COMMAND_PREVIEW_CHARS]}..."

    @staticmethod
    def _build_signal_command(pid: int, start_ticks: str, signal: SignalDelivery) -> str:
        return f"{_PYTHON} -c {shlex.quote(SIGNAL_SCRIPT)} {pid} {shlex.quote(start_ticks)} {shlex.quote(signal)}"

    @staticmethod
    def _tail_header_reserve_chars() -> int:
        largest_offset = str(BACKGROUND_LOG_MAX_BYTES)
        return len(f"{BYTE_COUNT_MARKER}{largest_offset} {largest_offset} 0\n")

    @staticmethod
    def _parse_tail_output(output: str) -> tuple[int, int, bool, str]:
        header, _, content = output.partition("\n")
        try:
            total_bytes_text, next_offset_text, is_truncated_text = header.removeprefix(BYTE_COUNT_MARKER).split()
            return int(total_bytes_text), int(next_offset_text), bool(int(is_truncated_text)), content
        except ValueError as error:
            raise SandboxError(f"Could not read the background log. The sandbox returned unexpected output: {output[:ERROR_PREVIEW_CHARS]!r}.") from error
