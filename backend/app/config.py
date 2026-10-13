from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_prefix="SRE_")

    database_url: str = "postgresql+psycopg://sre:sre@localhost:5432/sre"
    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
