from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True
    database_url: str
    llm_model: str = "gemma4:e2b"
    ollama_base_url: str = "http://localhost:11434"
    secret_key: str
    access_token_expire_minutes: int = 60
    clova_speech_invoke_url: str = ""
    clova_speech_secret: str = ""


settings = Settings()
