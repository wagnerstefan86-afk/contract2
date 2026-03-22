from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    virustotal_api_key: str = ""
    urlscan_api_key: str = ""
    urlscan_visibility: str = "private"
    llm_model: str = "gpt-4o"
    max_poll_seconds: int = 120
    poll_interval_seconds: int = 5
    database_url: str = "sqlite:///./mailscope.db"
    max_upload_size_mb: int = 25
    log_level: str = "INFO"

    # Service toggles
    enable_virustotal: bool = True
    enable_urlscan: bool = True
    enable_llm: bool = True

    # Optional access token for test deployments
    app_access_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
