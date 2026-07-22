from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import HttpUrl

class Settings(BaseSettings):
    VERI_EMAIL: str
    VERI_PASSWORD: str
    VERI_BASE_URL: HttpUrl
    HEADLESS: bool = False
    # Tamanho da janela do navegador (modo visível). Padrão cabe em telas 1366x768.
    WINDOW_WIDTH: int = 1280
    WINDOW_HEIGHT: int = 720

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
