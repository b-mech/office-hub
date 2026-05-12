import logging

from pydantic import Field
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid import UUID


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    minio_endpoint: str = Field(alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    imap_host: str = Field(alias="IMAP_HOST")
    imap_user: str = Field(alias="IMAP_USER")
    imap_password: str = Field(alias="IMAP_PASSWORD")
    imap_folder: str = Field(alias="IMAP_FOLDER")
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    active_model_provider: str = Field(alias="ACTIVE_MODEL_PROVIDER")
    secret_key: str = Field(alias="SECRET_KEY")
    office_hub_api_key: str = Field(alias="OFFICE_HUB_API_KEY")
    default_org_id: UUID = Field(alias="DEFAULT_ORG_ID")
    default_user_id: UUID = Field(alias="DEFAULT_USER_ID")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,https://mail.google.com",
        alias="CORS_ORIGINS",
    )
    cors_origin_regex: str = Field(
        default=r"(chrome-extension://.*|http://192\.168\.\d+\.\d+:3000)",
        alias="CORS_ORIGIN_REGEX",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()
            if error["type"] == "missing"
        ]
        if missing:
            logger.critical("Missing required environment variables: %s", ", ".join(missing))
        else:
            logger.critical("Invalid environment configuration: %s", exc)
        raise RuntimeError("Office Hub cannot start with invalid environment configuration") from exc


settings = load_settings()
