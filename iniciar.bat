@echo off
rem Abre a versao para o navegador. E so dar dois cliques neste arquivo.
rem Na primeira vez, cria o ambiente do Python (.venv) e instala o Flask.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Preparando o programa pela primeira vez...
    where uv >nul 2>nul && (
        uv venv .venv && uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    ) || (
        py -3 -m venv .venv || python -m venv .venv
        .venv\Scripts\python.exe -m pip install -r requirements.txt
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Nao foi possivel preparar o Python. Instale o Python em https://www.python.org/downloads/
    echo e marque a opcao "Add python.exe to PATH" durante a instalacao.
    pause
    exit /b 1
)

.venv\Scripts\python.exe app_web.py %*
pause
