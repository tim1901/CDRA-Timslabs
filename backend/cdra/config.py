from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    parallel_api_key: str | None = None
    allowed_origins: str = "http://localhost:3000"
    request_timeout: int = 20
    max_sources_per_query: int = 6
    max_pages_per_company: int = 40
    user_agent: str = "CDRA-Timslabs/0.1 (+https://timslabs.com)"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
