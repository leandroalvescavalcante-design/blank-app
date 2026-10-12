@echo off
setlocal
chcp 65001 >nul
title Ferramenta de Gestao Industrial
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo A ferramenta ainda nao foi instalada. Rode instalador\instalar_windows.bat primeiro.
    pause
    exit /b 1
)
echo Abrindo a ferramenta no navegador (http://localhost:8501).
rem servidor do app do celular, numa janela minimizada (se o Windows perguntar, permita em "Redes privadas")
start "Celular - Gestao Industrial" /min ".venv\Scripts\python.exe" -m app.movel.servidor
echo NAO feche esta janela enquanto estiver usando. Para encerrar, feche-a.
".venv\Scripts\python.exe" -m streamlit run streamlit_app.py --server.headless false
taskkill /fi "WINDOWTITLE eq Celular - Gestao Industrial*" >nul 2>&1
pause
endlocal
