from __future__ import annotations

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOCK = "mock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./artha.db"

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_llm_provider: LLMProviderName = LLMProviderName.MOCK

    # Application
    log_level: str = "INFO"
    environment: Environment = Environment.DEVELOPMENT

    # Orchestrator
    max_orchestrator_loops: int = 3
    default_llm_temperature: float = 0.0

    # Kill switch
    execution_enabled: bool = True


settings = Settings()
