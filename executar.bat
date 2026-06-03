@echo off
echo Iniciando Robo de Automacao Fiscal...
set PYTHONPATH=.
call .\venv\Scripts\activate.bat
python -m src.extractors.veri_scraper
pause
