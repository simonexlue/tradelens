from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    AWS_REGION: str
    AWS_S3_BUCKET: str
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str

    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    SUPABASE_JWT_SECRET: str | None = None

    FRONTEND_ORIGINS: List[str] = [
        "http://localhost:3000",
        "https://tradelens-frontend-one.vercel.app"
    ]

    openai_api_key: str | None = None

    class Config: 
        env_file = ".env"

settings = Settings()