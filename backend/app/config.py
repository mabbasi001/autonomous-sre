from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_prefix="SRE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sre:sre@localhost:5432/sre"
    log_level: str = "INFO"
    environment: str = "development"
    slack_webhook_url: str = ""
    oidc_tenant_id: str = ""
    oidc_client_id: str = ""
    oidc_jwks: str = ""  # inline JWKS JSON; when empty the tenant's JWKS endpoint is fetched
    approval_ttl_seconds: int = 900
    command_expiry_seconds: int = 120
    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "SRE_ANTHROPIC_API_KEY")
    )
    ai_model: str = "claude-opus-4-8"
    ai_timeout_seconds: int = 60
    ai_max_output_tokens: int = 2000
    ai_evidence_max_chars: int = 12000
    ai_token_budget: int = 20000


settings = Settings()
