from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://contract_review:changeme@db:5432/contract_review"
    upload_dir: str = "/data/uploads"
    secret_key: str = "changeme"

    # Initial admin: created/promoted on startup if set
    initial_admin_email: str = ""
    initial_admin_password: str = ""
    initial_admin_name: str = "Administrator"

    model_config = {"env_file": ".env"}


settings = Settings()
