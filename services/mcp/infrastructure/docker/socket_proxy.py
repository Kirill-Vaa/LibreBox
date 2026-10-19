import asyncio
import contextlib
import json
import os
import re
import signal
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final

import aiohttp

from config.constants import SANDBOX_CONTAINER_NAME, SANDBOX_CONTAINER_NAME_REGEX
from domain.generation import SandboxGeneration
from infrastructure.docker.constants import DOCKER_CONTAINER_GONE_STATUSES, DOCKER_PROXY_DEFAULT_SOCKET_PATH, DOCKER_PROXY_IO_TIMEOUT_SECONDS, DOCKER_PROXY_MAX_BODY_BYTES, DOCKER_PROXY_MAX_CONNECTIONS, DOCKER_PROXY_MAX_EXEC_GRANTS, DOCKER_PROXY_MAX_HEADER_BYTES, DOCKER_PROXY_PORT, DOCKER_PROXY_PUMP_CHUNK_BYTES, DOCKER_PROXY_RELAY_MAX_SECONDS, DOCKER_PROXY_SANDBOX_CACHE_SECONDS, DOCKER_PROXY_SHUTDOWN_GRACE_SECONDS
from utils.logger import logger


_HEADER_TERMINATOR: Final[bytes] = b"\r\n\r\n"
_PUBLIC_PATHS: Final[frozenset[str]] = frozenset({"/_ping", "/version"})
_EXEC_CREATE_FIELDS: Final[frozenset[str]] = frozenset({"AttachStderr", "AttachStdin", "AttachStdout", "Cmd", "Container", "Env", "Privileged", "Tty", "User", "WorkingDir", "detachKeys"})
_EXEC_START_FIELDS: Final[frozenset[str]] = frozenset({"Detach", "Tty"})

_ROUTE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:/v[0-9]+\.[0-9]+)?(/[^?]*)")
_HEADER_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_CONTAINER_PATTERN: Final[re.Pattern[str]] = re.compile(rf"/containers/({SANDBOX_CONTAINER_NAME_REGEX})/(json|exec)")
_EXEC_PATTERN: Final[re.Pattern[str]] = re.compile(r"/exec/([a-f0-9]{64})/(json|start)")


class ProxyRequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CachedSandbox:
    generation: SandboxGeneration
    expires_at: float


@dataclass(frozen=True)
class ProxyRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class DockerSocketProxy:
    def __init__(self, socket_path: str, container_name: str) -> None:
        self._socket_path = socket_path
        self._container_name = container_name
        self._session: aiohttp.ClientSession | None = None
        self._exec_grants: OrderedDict[str, SandboxGeneration] = OrderedDict()
        self._streaming_execs: dict[str, int] = {}
        self._cached_sandbox: CachedSandbox | None = None
        self._sandbox_lock = asyncio.Lock()
        self._open_connections = 0
        self._connection_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        connector = aiohttp.UnixConnector(path=self._socket_path)
        timeout = aiohttp.ClientTimeout(total=DOCKER_PROXY_IO_TIMEOUT_SECONDS)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout, auto_decompress=False)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def drain_connections(self) -> None:
        connection_tasks = list(self._connection_tasks)
        if not connection_tasks:
            return

        _, pending_tasks = await asyncio.wait(connection_tasks, timeout=DOCKER_PROXY_SHUTDOWN_GRACE_SECONDS)
        if pending_tasks:
            logger.warning(f"Docker proxy is closing {len(pending_tasks)} connections that outlived the {DOCKER_PROXY_SHUTDOWN_GRACE_SECONDS} s shutdown grace")

        for pending_task in pending_tasks:
            pending_task.cancel()

        await asyncio.gather(*pending_tasks, return_exceptions=True)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection_task = asyncio.current_task()
        if connection_task is not None:
            self._connection_tasks.add(connection_task)
            connection_task.add_done_callback(self._connection_tasks.discard)

        if self._open_connections >= DOCKER_PROXY_MAX_CONNECTIONS:
            logger.warning(f"Docker proxy refused a connection, {self._open_connections} are already open")
            with contextlib.suppress(ConnectionError, OSError):
                await self._respond(writer, 503, b'{"message":"Too many concurrent connections"}')

            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

            return

        self._open_connections += 1
        try:
            async with asyncio.timeout(DOCKER_PROXY_IO_TIMEOUT_SECONDS):
                request = await self._read_request(reader)
                should_upgrade = await self._dispatch(request, writer)

            if should_upgrade:
                exec_match = _EXEC_PATTERN.fullmatch(request.path)
                if exec_match is None:
                    raise ProxyRequestError(403, "Docker API route is not allowed")

                streaming_exec_id = exec_match.group(1)
                self._mark_exec_streaming(streaming_exec_id)
                try:
                    await self._upgrade(request.path, request.body, reader, writer)
                finally:
                    self._unmark_exec_streaming(streaming_exec_id)
        except ProxyRequestError as proxy_request_error:
            await self._respond(writer, proxy_request_error.status, json.dumps({"message": str(proxy_request_error)}).encode())
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as parse_error:
            logger.debug(f"Invalid Docker proxy request: {parse_error}")
            await self._respond(writer, 400, b'{"message":"Invalid request"}')
        except (aiohttp.ClientError, OSError, TimeoutError) as connection_error:
            logger.warning(f"Docker proxy connection failed: {connection_error}")
            if not writer.is_closing():
                with contextlib.suppress(ConnectionError):
                    await self._respond(writer, 502, b'{"message":"Docker daemon unavailable"}')
        finally:
            self._open_connections -= 1
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def _dispatch(self, request: ProxyRequest, writer: asyncio.StreamWriter) -> bool:
        if request.method == "GET" and request.path in _PUBLIC_PATHS:
            await self._forward(request.method, request.path, writer)
            return False

        container_match = _CONTAINER_PATTERN.fullmatch(request.path)
        if container_match is not None:
            identifier, operation = container_match.groups()
            if request.method == "GET" and operation == "json":
                container, generation = await self._refresh_sandbox()
                if identifier not in {self._container_name, generation.container_id}:
                    raise ProxyRequestError(403, "Only the sandbox container is allowed")

                await self._respond(writer, 200, json.dumps(container).encode())
                return False

            generation = await self._sandbox()
            if identifier not in {self._container_name, generation.container_id}:
                raise ProxyRequestError(403, "Only the sandbox container is allowed")

            if request.method != "POST" or operation != "exec":
                raise ProxyRequestError(403, "Docker API route is not allowed")

            await self._create_exec(request.body, generation, writer)
            return False

        generation = await self._sandbox()
        exec_match = _EXEC_PATTERN.fullmatch(request.path)
        if exec_match is None:
            raise ProxyRequestError(403, "Docker API route is not allowed")

        exec_id, operation = exec_match.groups()
        if self._exec_grants.get(exec_id) != generation:
            raise ProxyRequestError(403, "Exec was not created for the current sandbox through this proxy")

        self._exec_grants.move_to_end(exec_id)

        if request.method == "GET" and operation == "json":
            await self._forward(request.method, request.path, writer)
            return False

        if request.method != "POST" or operation != "start":
            raise ProxyRequestError(403, "Docker API operation is not allowed")

        self._validate_exec_start(request)
        return True

    async def _create_exec(self, body: bytes, generation: SandboxGeneration, writer: asyncio.StreamWriter) -> None:
        configuration = self._parse_json_object(body)
        if set(configuration) - _EXEC_CREATE_FIELDS or configuration.get("Privileged", False):
            raise ProxyRequestError(403, "Exec configuration is not allowed")

        requested_container = configuration.get("Container")
        if requested_container is not None and requested_container not in {self._container_name, generation.container_id}:
            raise ProxyRequestError(403, "Only the sandbox container is allowed")

        status, payload, content_type = await self._request("POST", f"/containers/{generation.container_id}/exec", body)
        if status == 201:
            try:
                created = json.loads(payload)
                if not isinstance(created, dict):
                    raise TypeError("expected a JSON object")

                exec_id = str(created["Id"])
            except (ValueError, TypeError, KeyError) as payload_error:
                logger.error(f"Docker daemon created an exec without a usable Id, leaving it orphaned on container={generation.container_id}: {payload_error}")
                raise ProxyRequestError(502, "Docker daemon returned an unusable exec response") from payload_error

            self._grant_exec(exec_id, generation)
        elif status in DOCKER_CONTAINER_GONE_STATUSES:
            self._cached_sandbox = None

        await self._respond(writer, status, payload, content_type)

    def _validate_exec_start(self, request: ProxyRequest) -> None:
        configuration = self._parse_json_object(request.body)
        if set(configuration) - _EXEC_START_FIELDS or configuration.get("Detach") is not False:
            raise ProxyRequestError(403, "Only attached exec streams are allowed")

        if request.headers.get("upgrade", "").lower() != "tcp":
            raise ProxyRequestError(400, "TCP upgrade is required")

    def _grant_exec(self, exec_id: str, generation: SandboxGeneration) -> None:
        self._exec_grants[exec_id] = generation
        if len(self._exec_grants) <= DOCKER_PROXY_MAX_EXEC_GRANTS:
            return

        evicted_exec_id = next((granted_exec_id for granted_exec_id in self._exec_grants if granted_exec_id != exec_id and granted_exec_id not in self._streaming_execs), None)
        if evicted_exec_id is not None:
            del self._exec_grants[evicted_exec_id]

    def _mark_exec_streaming(self, exec_id: str) -> None:
        self._streaming_execs[exec_id] = self._streaming_execs.get(exec_id, 0) + 1

    def _unmark_exec_streaming(self, exec_id: str) -> None:
        remaining_streams = self._streaming_execs.get(exec_id, 0) - 1
        if remaining_streams > 0:
            self._streaming_execs[exec_id] = remaining_streams
            return

        self._streaming_execs.pop(exec_id, None)
        if exec_id in self._exec_grants:
            self._exec_grants.move_to_end(exec_id)

    async def _sandbox(self) -> SandboxGeneration:
        cached_sandbox = self._cached_sandbox
        if cached_sandbox is not None and asyncio.get_running_loop().time() < cached_sandbox.expires_at:
            return cached_sandbox.generation

        async with self._sandbox_lock:
            cached_sandbox = self._cached_sandbox
            if cached_sandbox is not None and asyncio.get_running_loop().time() < cached_sandbox.expires_at:
                return cached_sandbox.generation

            _, generation = await self._inspect_sandbox()
            return generation

    async def _refresh_sandbox(self) -> tuple[dict[str, Any], SandboxGeneration]:
        async with self._sandbox_lock:
            return await self._inspect_sandbox()

    async def _inspect_sandbox(self) -> tuple[dict[str, Any], SandboxGeneration]:
        status, payload, _ = await self._request("GET", f"/containers/{self._container_name}/json")
        if status != 200:
            self._cached_sandbox = None
            raise ProxyRequestError(status, "Sandbox container is unavailable")

        container: dict[str, Any] = json.loads(payload)
        generation = SandboxGeneration(container["Id"], container["State"]["StartedAt"])

        if self._cached_sandbox is None or self._cached_sandbox.generation != generation:
            self._exec_grants = OrderedDict((exec_id, granted_generation) for exec_id, granted_generation in self._exec_grants.items() if granted_generation == generation)

        self._cached_sandbox = CachedSandbox(generation, asyncio.get_running_loop().time() + DOCKER_PROXY_SANDBOX_CACHE_SECONDS)
        return container, generation

    async def _forward(self, method: str, path: str, writer: asyncio.StreamWriter) -> None:
        status, payload, content_type = await self._request(method, path)
        await self._respond(writer, status, payload, content_type)

    async def _request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
        if self._session is None:
            raise RuntimeError("Docker proxy is not started")

        async with self._session.request(method, f"http://docker{path}", data=body, headers={"Content-Type": "application/json"}, allow_redirects=False) as response:
            payload = await response.read()
            content_type = response.headers.get("Content-Type", "application/json")
            return response.status, payload, content_type

    async def _upgrade(self, path: str, body: bytes, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        async with asyncio.timeout(DOCKER_PROXY_IO_TIMEOUT_SECONDS):
            daemon_reader, daemon_writer = await asyncio.open_unix_connection(self._socket_path, limit=DOCKER_PROXY_MAX_HEADER_BYTES)

        try:
            request_headers = f"POST {path} HTTP/1.1\r\nHost: docker\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n".encode()
            daemon_writer.write(request_headers + body)
            await daemon_writer.drain()

            async with asyncio.timeout(DOCKER_PROXY_IO_TIMEOUT_SECONDS):
                response_headers = await daemon_reader.readuntil(_HEADER_TERMINATOR)

            if response_headers.split(b" ", 2)[1] != b"101":
                raise ProxyRequestError(502, "Docker daemon rejected the exec stream upgrade")

            client_writer.write(response_headers)
            await client_writer.drain()
            await self._relay(client_reader, client_writer, daemon_reader, daemon_writer)
        finally:
            daemon_writer.close()
            with contextlib.suppress(ConnectionError):
                await daemon_writer.wait_closed()

    @staticmethod
    async def _read_request(reader: asyncio.StreamReader) -> ProxyRequest:
        try:
            header_bytes = await reader.readuntil(_HEADER_TERMINATOR)
        except asyncio.LimitOverrunError as overrun_error:
            raise ProxyRequestError(431, "Request headers are too large") from overrun_error

        request_line, *header_lines = header_bytes.decode("ascii").split("\r\n")
        method, target, protocol = request_line.split(" ")
        if protocol != "HTTP/1.1":
            raise ProxyRequestError(400, "HTTP/1.1 is required")

        headers: dict[str, str] = {}
        for header_line in filter(None, header_lines):
            name, value = header_line.split(":", 1)
            if _HEADER_NAME_PATTERN.fullmatch(name) is None:
                raise ProxyRequestError(400, "Header name is not a valid token")

            name = name.lower()
            if name in headers:
                raise ProxyRequestError(400, "Duplicate headers are not allowed")

            headers[name] = value.strip()

        if "transfer-encoding" in headers:
            raise ProxyRequestError(400, "Chunked requests are not allowed")

        body_length = int(headers.get("content-length", "0"))
        if not 0 <= body_length <= DOCKER_PROXY_MAX_BODY_BYTES:
            raise ProxyRequestError(413, "Request body is too large")

        body = await reader.readexactly(body_length)
        route_match = _ROUTE_PATTERN.fullmatch(target)
        if route_match is None:
            raise ProxyRequestError(403, "Docker API route is not allowed")

        return ProxyRequest(method=method, path=route_match.group(1), headers=headers, body=body)

    @staticmethod
    def _parse_json_object(body: bytes) -> dict[str, Any]:
        configuration = json.loads(body)
        if not isinstance(configuration, dict):
            raise ProxyRequestError(400, "Expected a JSON object")

        return configuration

    @staticmethod
    async def _relay(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter, daemon_reader: asyncio.StreamReader, daemon_writer: asyncio.StreamWriter) -> None:
        to_daemon = asyncio.create_task(DockerSocketProxy._pump(client_reader, daemon_writer))
        to_client = asyncio.create_task(DockerSocketProxy._pump(daemon_reader, client_writer))
        try:
            async with asyncio.timeout(DOCKER_PROXY_RELAY_MAX_SECONDS):
                await asyncio.wait((to_daemon, to_client), return_when=asyncio.FIRST_COMPLETED)
                if to_client.done():
                    to_daemon.cancel()
                else:
                    await asyncio.shield(to_client)
        except TimeoutError:
            logger.warning(f"Docker proxy abandoned an exec stream after {DOCKER_PROXY_RELAY_MAX_SECONDS} s")
        finally:
            for task in (to_daemon, to_client):
                task.cancel()

            await asyncio.gather(to_daemon, to_client, return_exceptions=True)

    @staticmethod
    async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(DOCKER_PROXY_PUMP_CHUNK_BYTES):
                writer.write(data)
                await writer.drain()
        except OSError as stream_error:
            logger.debug(f"Docker proxy exec stream ended early: {stream_error}")
        finally:
            if writer.can_write_eof() and not writer.is_closing():
                with contextlib.suppress(OSError):
                    writer.write_eof()

    @staticmethod
    def _status_phrase(status: int) -> str:
        try:
            return HTTPStatus(status).phrase
        except ValueError:
            return "Unknown"

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, status: int, payload: bytes, content_type: str = "application/json") -> None:
        headers = f"HTTP/1.1 {status} {DockerSocketProxy._status_phrase(status)}\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
        writer.write(headers + payload)
        await writer.drain()


async def main() -> None:
    proxy = DockerSocketProxy(os.environ.get("DOCKER_SOCKET_PATH", DOCKER_PROXY_DEFAULT_SOCKET_PATH), SANDBOX_CONTAINER_NAME)
    await proxy.start()

    shutdown_event = asyncio.Event()
    running_loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        running_loop.add_signal_handler(shutdown_signal, shutdown_event.set)

    try:
        server = await asyncio.start_server(proxy.handle, "0.0.0.0", DOCKER_PROXY_PORT, limit=DOCKER_PROXY_MAX_HEADER_BYTES)
        async with server:
            logger.info(f"Docker socket proxy listening port={DOCKER_PROXY_PORT} sandbox={SANDBOX_CONTAINER_NAME}")
            await shutdown_event.wait()
            server.close()
            await proxy.drain_connections()
    finally:
        await proxy.close()
        logger.info("Docker socket proxy stopped")


if __name__ == "__main__":
    asyncio.run(main())
