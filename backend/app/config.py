from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://contract_review:changeme@db:5432/contract_review"
    upload_dir: str = "/data/uploads"
    secret_key: str = "changeme"

    model_config = {"env_file": ".env"}


settings = Settings()
