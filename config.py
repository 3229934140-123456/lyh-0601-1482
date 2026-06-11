from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI数据标注协作服务"
    APP_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "sqlite:///./annotation.db"
    DATABASE_ECHO: bool = False

    LOCK_TIMEOUT_SECONDS: int = 1800
    DEFAULT_SAMPLES_PER_TASK: int = 50
    DEFAULT_ANNOTATORS_PER_SAMPLE: int = 2
    DEFAULT_QUALITY_SAMPLE_RATE: float = 0.1
    CONSISTENCY_THRESHOLD: float = 0.8

    EXPORT_DIR: str = "./exports"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
