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
echo NAO feche esta janela enquanto estiver usando. Para encerrar, feche-a.
".venv\Scripts\python.exe" -m streamlit run streamlit_app.py --server.headless false
pause
endlocal
