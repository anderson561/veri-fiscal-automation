@echo off
echo Criando Executavel (.exe) do Robo...
call .\venv\Scripts\activate.bat

echo Instalando/Atualizando dependencias (PyInstaller)...
pip install pyinstaller

echo Gerando Executavel...
pyinstaller --noconfirm --onefile --console --name "VeriFiscal" ^
    --add-data "src;src" ^
    --collect-all playwright ^
    --collect-all reportlab ^
    --hidden-import pydantic_settings ^
    --hidden-import pdfplumber ^
    --hidden-import loguru ^
    --hidden-import pydantic ^
    --hidden-import dotenv ^
    --hidden-import tenacity ^
    "src/extractors/veri_scraper.py"

echo.
echo Copiando arquivo .env para a pasta dist...
copy .env dist\.env

echo.
echo Executavel gerado na pasta 'dist'.
echo Lembre-se que o Playwright precisa dos browsers instalados no sistema.
pause
