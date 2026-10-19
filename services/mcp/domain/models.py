from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


BackgroundStatus = Literal["running", "exited", "lost", "sandbox_restarted"]
FileSearchMode = Literal["content", "files"]
SignalName = Literal["CONT", "HUP", "INT", "KILL", "QUIT", "STOP", "TERM", "USR1", "USR2"]


class ShellResult(BaseModel):
    stdout: str = Field(description="Standard output of the command. If it exceeds the output limit, the middle is replaced with a [... N chars truncated ...] marker.")
    stderr: str = Field(description="Standard error of the command. Truncated the same way as stdout.")
    exit_code: int | None = Field(description="Exit code of the command, or null if it was killed before reporting one.")
    truncated: bool = Field(description="True if stdout or stderr was cut to fit the output limit. Rerun with the output redirected to a file to see all of it.")
    duration_ms: int = Field(description="Wall-clock run time of the command, in milliseconds.")
    timed_out: bool = Field(description="True if the command reached its timeout and was terminated. Raise timeout or use background_start.")


class BackgroundProcessInfo(BaseModel):
    process_id: str = Field(description="ID of the background process, made of lowercase letters and digits. Pass it to the other background tools.")
    pid: int = Field(description="Process ID of the process group leader inside the sandbox.")
    command: str = Field(description="Command text as started. A very long command is shortened and ends with ...")
    status: BackgroundStatus = Field(description="One of running, exited, lost (vanished without an exit code) or sandbox_restarted (process gone after a sandbox restart). Log stays readable via background_tail unless the sandbox was recreated.")
    exit_code: int | None = Field(default=None, description="Exit code once the process has exited, otherwise null. A process ended by signal N reports 128 + N.")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="UTC time the process started, in ISO 8601.")


class BackgroundTailResult(BaseModel):
    process_id: str = Field(description="ID of the background process whose log was read.")
    content: str = Field(description="Requested part of the log.")
    total_bytes: int = Field(description="Size of the log in bytes when it was read.")
    next_offset: int = Field(description="Byte offset right after content. Pass it as offset_bytes to read on, until it equals total_bytes. In last-lines mode it already equals total_bytes, so it marks where new output will start.")
    truncated: bool = Field(default=False, description="True if the last lines did not fit the output limit, so only their end is returned. Read the earlier part with offset_bytes.")


class BackgroundWaitResult(BaseModel):
    process_id: str = Field(description="ID of the background process that was waited for.")
    status: BackgroundStatus = Field(description="Status when the wait ended. running means the wait timed out. Other values are described by background_status.")
    exit_code: int | None = Field(description="Exit code once the process has exited, otherwise null.")
    tail: str = Field(description="Last lines of the log when the wait ended. Empty if the log could not be read. Read more with background_tail.")
    truncated: bool = Field(default=False, description="True if the last lines did not fit the output limit, so tail holds only their end. Read the rest with background_tail.")


class BackgroundListResult(BaseModel):
    processes: list[BackgroundProcessInfo] = Field(description="Current state of every tracked background process.")


class FileReadResult(BaseModel):
    path: str = Field(description="Absolute path of the file.")
    content: str = Field(description="Requested lines, each as its 1-based number, a tab and the text. Line endings are removed. Empty for a binary file.")
    is_binary: bool = Field(description="True if the file was detected as binary and not decoded. Inspect it with shell_execute.")
    size_bytes: int = Field(description="Size of the file in bytes.")
    line_count: int = Field(description="Total number of lines in the file, not only the returned ones. 0 for a binary file.")
    next_offset: int = Field(description="Offset of the line after the last returned one. Pass it as offset to read on.")
    truncated: bool = Field(default=False, description="True if content was cut at the per-call character limit. Continue with offset=next_offset.")


class FileWriteResult(BaseModel):
    path: str = Field(description="Absolute path of the file.")
    bytes_written: int = Field(description="Number of bytes written, after encoding.")


class FileEditResult(BaseModel):
    path: str = Field(description="Absolute path of the file.")
    replacements: int = Field(description="Number of occurrences replaced.")


class FileSearchResult(BaseModel):
    matches: list[str] = Field(description="Results in the order found. Content mode: lines as absolute_path:line:text. Files mode: absolute paths.")
    truncated: bool = Field(default=False, description="True if more results exist beyond max_results. Narrow pattern, path or glob, or raise max_results.")
    timed_out: bool = Field(default=False, description="True if the search reached its time limit, so matches are partial. Narrow pattern, path or glob.")


class DirectoryResult(BaseModel):
    path: str = Field(description="Absolute path of the directory.")


class TreeNode(BaseModel):
    name: str = Field(description="Name of the entry.")
    path: str = Field(description="Absolute path of the entry.")
    is_dir: bool = Field(description="True if the entry is a directory.")
    size_bytes: int = Field(description="Size of a file in bytes, or the total size of everything inside a directory. 0 for every entry when show_sizes is false.")
    children: list[TreeNode] = Field(default_factory=list, description="Entries inside a directory, down to max_depth. Empty for files and for directories at the depth limit.")


class DirectoryTreeResult(BaseModel):
    root: TreeNode = Field(description="Tree of the requested path.")
    truncated: bool = Field(default=False, description="True if the entry limit was reached and some entries were left out. Lower max_depth or use a narrower path.")


class InventoryCommand(BaseModel):
    name: str = Field(description="Command name found on PATH when the image was built.")
    path: str = Field(description="Command path resolved with command -v during the image build.")
    version: str | None = Field(description="Captured version string, or null if no version probe succeeded.")
    is_security: bool = Field(description="True if the command was added by the image's security installation stage.")


class SandboxInventory(BaseModel):
    profile: Literal["core", "standard", "full"] = Field(description="Sandbox image profile recorded at build time.")
    commands: list[InventoryCommand] = Field(description="All commands in the build-time snapshot.")
    toolchain_commands: list[str] = Field(description="Names of the primary command-line tools listed in the compact summary.")

    @model_validator(mode="after")
    def validate_toolchain_commands(self) -> Self:
        if not set(self.toolchain_commands).issubset(command.name for command in self.commands):
            raise ValueError("Toolchain summary references commands absent from the inventory")

        return self


class SleepResult(BaseModel):
    slept_seconds: float = Field(description="Seconds actually slept.")


class TimeNowResult(BaseModel):
    iso: str = Field(description="Current time in the requested timezone, in ISO 8601.")
    epoch: float = Field(description="Current time as Unix epoch seconds.")
    human: str = Field(description="Current time as YYYY-MM-DD HH:MM:SS followed by the timezone abbreviation.")
    timezone: str = Field(description="IANA name of the timezone the time is expressed in.")
