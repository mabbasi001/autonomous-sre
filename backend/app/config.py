from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_prefix="SRE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sre:sre@localhost:5432/sre"
    migration_database_url: str = ""  # falls back to database_url
    log_level: str = "INFO"
    environment: str = "development"
    slack_webhook_url: str = ""
    oidc_tenant_id: str = ""
    oidc_client_id: str = ""
    oidc_jwks: str = ""  # inline JWKS JSON; when empty the tenant's JWKS endpoint is fetched
    auth_secret: str = ""  # HS256 key for local-account session tokens (interim, pre-Entra)
    session_ttl_seconds: int = 43200  # 12h local-login session lifetime
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
    verify_settle_seconds: int = 10
    verify_max_attempts: int = 2


settings = Settings()
