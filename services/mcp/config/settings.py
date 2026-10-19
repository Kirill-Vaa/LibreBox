import sys
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS, OUTPUT_CHAR_LIMIT_DEFAULT, TOOL_TIMEOUT_MAX_SECONDS
from utils.logger import logger


type LogLevel = Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]


class _ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    log_level: LogLevel = "INFO"
    log_serialize: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class AppSettings(_ServiceSettings):
    default_command_timeout_seconds: int = Field(default=DEFAULT_COMMAND_TIMEOUT_SECONDS, gt=0, le=TOOL_TIMEOUT_MAX_SECONDS)
    egress_allow_cidrs: str = ""
    egress_block_cidrs: str = ""
    output_char_limit: int = Field(default=OUTPUT_CHAR_LIMIT_DEFAULT, gt=0)


class AuthGateSettings(_ServiceSettings):
    jwt_refresh_secret: SecretStr = Field(min_length=1)
    mongo_uri: SecretStr = Field(min_length=1)


def _load[SettingsType: BaseSettings](settings_class: type[SettingsType]) -> SettingsType:
    try:
        return settings_class()
    except ValidationError as error:
        for validation_issue in error.errors():
            field_name = ".".join(str(location) for location in validation_issue["loc"]) or "settings"
            logger.critical(f"Invalid configuration {field_name}: {validation_issue['msg']}")
        sys.exit(1)


def load_app_settings() -> AppSettings:
    return _load(AppSettings)


def load_auth_gate_settings() -> AuthGateSettings:
    return _load(AuthGateSettings)
