from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS Credentials
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # AWS Bedrock
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_kb_id: str | None = None

    # S3
    s3_bucket_name: str | None = None # Optional for Aurora flow

    # OpenAI
    openai_api_key: str
    openai_chat_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"

    # Aurora PostgreSQL
    db_host: str | None = None
    db_name: str = "postgres"
    db_user: str = "postgres"
    db_password: str | None = None
    db_port: int = 5432

    # Crawler
    max_crawl_depth: int = 2
    max_pages_per_crawl: int = 50
    crawl_concurrency: int = 5

    # App
    log_level: str = "INFO"
    jwt_secret_key: str | None = None
    jwt_access_token_exp_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
