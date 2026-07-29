from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True
    database_url: str
    llm_model: str = "gemma4:e2b"
    embed_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"
    secret_key: str
    access_token_expire_minutes: int = 60
    clova_speech_invoke_url: str = ""
    clova_speech_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_calendar_redirect_uri: str = ""
    google_calendar_timezone: str = "Asia/Seoul"
    google_calendar_reminder_minutes: int = 1440
    token_encryption_key: str = ""
    mcp_issuer_url: str = "http://localhost:8000"
    mcp_resource_server_url: str = "http://localhost:8000/mcp"
    static_asset_base_url: str = ""
    static_asset_version: str = ""


settings = Settings()
