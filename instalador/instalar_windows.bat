@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Instalador - Ferramenta de Gestao Industrial
cd /d "%~dp0.."

echo.
echo  ==========================================================
echo   Ferramenta de Gestao Industrial - instalacao
echo  ==========================================================
echo.

rem ---------------------------------------------------------- 1. Python 3.11 ou mais novo
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo  [1/4] Python 3.11 ou mais novo nao encontrado.
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  Instale o Python manualmente em https://www.python.org/downloads/
        echo  e MARQUE a opcao "Add python.exe to PATH". Depois rode este instalador de novo.
        goto :falha
    )
    echo        Instalando o Python 3.12 pelo winget. Aceite as perguntas que aparecerem.
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo  A instalacao do Python falhou. Instale manualmente em https://www.python.org/downloads/
        goto :falha
    )
    echo.
    echo  Python instalado. FECHE esta janela e rode o instalador de novo
    echo  para o Windows reconhecer o Python recem-instalado.
    goto :fim
)
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do set "PYVER=%%v"
echo  [1/4] Python %PYVER% encontrado.

rem ---------------------------------------------------------- 2. ambiente isolado
if not exist ".venv\Scripts\python.exe" (
    echo  [2/4] Criando o ambiente da ferramenta...
    %PY% -m venv .venv
    if errorlevel 1 goto :falha
) else (
    echo  [2/4] Ambiente da ferramenta ja existe.
)

rem ---------------------------------------------------------- 3. bibliotecas
echo  [3/4] Instalando as bibliotecas (precisa de internet; pode levar alguns minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 goto :falha
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 goto :falha

rem evita a pergunta de e-mail do Streamlit na primeira abertura
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" (
        echo [general]
        echo email = ""
    )
)

rem ---------------------------------------------------------- 4. atalho na area de trabalho
echo  [4/4] Criando o atalho "Gestao Industrial" na area de trabalho...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Gestao Industrial.lnk')); $s.TargetPath='%~dp0iniciar_windows.bat'; $s.WorkingDirectory='%~dp0..'; $s.Save()" >nul 2>&1
if errorlevel 1 echo        Nao foi possivel criar o atalho. Use instalador\iniciar_windows.bat.

echo.
choice /c SN /m " Carregar o cenario de TREINAMENTO (dados ficticios) agora"
if errorlevel 2 goto :pronto
echo  Carregando o cenario ficticio (cerca de 1 minuto)...
".venv\Scripts\python.exe" -m app.admin carregar-simulacao --usuario instalador
if errorlevel 1 echo  O cenario nao carregou. A ferramenta funciona mesmo assim.

:pronto
echo.
echo  ==========================================================
echo   Instalacao concluida.
echo   Para abrir: clique duas vezes no atalho "Gestao Industrial"
echo   na area de trabalho (ou em instalador\iniciar_windows.bat).
echo  ==========================================================
goto :fim

:falha
echo.
echo  A instalacao NAO terminou. Copie as mensagens acima e envie ao administrador.

:fim
echo.
pause
endlocal
