@echo off
REM ============================================================
REM  juntar.bat — Atalho de Consolidação do Escriba (Lexis)
REM ============================================================
REM  COMO USAR:
REM  1. Copie este arquivo para a pasta do canal desejado, OU
REM  2. Abra um terminal na pasta do canal e chame:
REM       C:\Users\Jandir\scripts\escriba\juntar.bat
REM       (ou adicione a pasta do Escriba ao PATH do sistema)
REM
REM  Modos:
REM    juntar.bat           → consolida a pasta onde o terminal está
REM    juntar.bat --reset   → apaga volumes e reprocessa
REM ============================================================

REM ── Localize o Escriba ──────────────────────────────────────
set "ESCRIBA_DIR=%USERPROFILE%\scripts\escriba"
if not exist "%ESCRIBA_DIR%\escriba.py" set "ESCRIBA_DIR=%USERPROFILE%\scripts\GitHub\escriba"
if not exist "%ESCRIBA_DIR%\escriba.py" set "ESCRIBA_DIR=%USERPROFILE%\Desktop\escriba"
if not exist "%ESCRIBA_DIR%\escriba.py" (
    echo.
    echo  [ERRO] Nao foi possivel localizar escriba.py
    echo  Esperado em: %USERPROFILE%\scripts\escriba\
    echo.
    pause
    exit /b 1
)

REM ── Python (venv > sistema) ──────────────────────────────────
set "PYTHON=%ESCRIBA_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

REM ── Flag de operação ────────────────────────────────────────
set "FLAG=--juntar"
if "%~1"=="--reset" set "FLAG=--lexis-reset"

REM ── Execução na pasta ATUAL do terminal (pasta do canal) ─────
echo.
echo  Escriba · Juntar  ^(Lexis^)
echo  ========================================
echo  Pasta  : %CD%
echo  Modo   : %FLAG%
echo  ========================================
echo.

"%PYTHON%" "%ESCRIBA_DIR%\escriba.py" %FLAG%

if errorlevel 1 (
    echo.
    echo  [ERRO] A consolidacao falhou.
    pause
) else (
    echo.
    echo  [OK] Consolidacao concluida com sucesso.
    timeout /t 3 /nobreak >nul
)
