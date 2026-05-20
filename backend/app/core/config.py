import os
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    minio_url: str = Field(alias="MINIO_URL")
    minio_root_user: str = Field(alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(alias="MINIO_ROOT_PASSWORD")
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
    environment: str = Field(alias="ENVIRONMENT")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,https://mail.google.com",
        alias="CORS_ORIGINS",
    )
    cors_origin_regex: str = Field(
        default=r"(chrome-extension://.*|http://192\.168\.\d+\.\d+:3000)",
        alias="CORS_ORIGIN_REGEX",
    )
    box_client_id: str = Field(default="", alias="BOX_CLIENT_ID")
    box_client_secret: str = Field(default="", alias="BOX_CLIENT_SECRET")
    box_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/box/oauth/callback",
        alias="BOX_REDIRECT_URI",
    )
    box_not_finalized_folder_id: str = Field(default="", alias="BOX_NOT_FINALIZED_FOLDER_ID")
    box_finalized_folder_id: str = Field(default="", alias="BOX_FINALIZED_FOLDER_ID")
    box_token_file: str = Field(default=".box_token.json", alias="BOX_TOKEN_FILE")
    docusign_integration_key: str = Field(default="", alias="DOCUSIGN_INTEGRATION_KEY")
    docusign_user_id: str = Field(default="", alias="DOCUSIGN_USER_ID")
    docusign_account_id: str = Field(default="", alias="DOCUSIGN_ACCOUNT_ID")
    docusign_private_key: str = Field(default="", alias="DOCUSIGN_PRIVATE_KEY")
    docusign_auth_server: str = Field(default="account-d.docusign.com", alias="DOCUSIGN_AUTH_SERVER")
    docusign_base_path: str = Field(default="https://demo.docusign.net/restapi", alias="DOCUSIGN_BASE_PATH")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def box_configured(self) -> bool:
        return bool(
            self.box_client_id
            and self.box_client_secret
            and self.box_not_finalized_folder_id
            and self.box_finalized_folder_id
        )

    @property
    def box_authenticated(self) -> bool:
        return os.path.exists(self.box_token_file)

    @property
    def docusign_configured(self) -> bool:
        return bool(
            self.docusign_integration_key
            and self.docusign_user_id
            and self.docusign_account_id
            and self.docusign_private_key
            and self.docusign_auth_server
            and self.docusign_base_path
        )


settings = Settings()
