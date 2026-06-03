from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import HttpUrl

class Settings(BaseSettings):
    VERI_EMAIL: str
    VERI_PASSWORD: str
    VERI_BASE_URL: HttpUrl
    HEADLESS: bool = False
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
