# ============================================================
# juntar.ps1 — Atalho de Consolidação do Escriba (Lexis)
# ============================================================
# Execute este script dentro de qualquer pasta de canal para
# gerar/atualizar os volumes do NotebookLM.
#
# Uso:
#   .\juntar.ps1              → consolida a pasta atual
#   .\juntar.ps1 --reset      → apaga volumes e reprocessa
#   .\juntar.ps1 C:\pasta     → consolida uma pasta específica
# ============================================================

param(
    [string]$TargetPath = "",
    [switch]$Reset
)

# --- Configuração ---
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$EscribaScript = Join-Path $ScriptDir "escriba.py"
$VenvPython    = Join-Path $ScriptDir ".venv\Scripts\python.exe"

# Usa Python do venv se existir, senão usa o do PATH
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = "python"
}

# Define pasta alvo
if ($TargetPath -ne "") {
    $WorkDir = Resolve-Path $TargetPath
} else {
    $WorkDir = Get-Location
}

# --- Banner ---
Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   Escriba · Juntar  (Lexis)          ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Pasta : " -NoNewline -ForegroundColor DarkGray
Write-Host "$WorkDir" -ForegroundColor White
Write-Host "  Modo  : " -NoNewline -ForegroundColor DarkGray
if ($Reset) {
    Write-Host "RESET (apaga e reprocessa volumes)" -ForegroundColor Yellow
} else {
    Write-Host "Incremental (apenas novos arquivos)" -ForegroundColor Green
}
Write-Host ""

# --- Execução ---
$Flag = if ($Reset) { "--lexis-reset" } else { "--juntar" }

Push-Location $WorkDir
try {
    & $PythonExe $EscribaScript $Flag
    $ExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

# --- Resultado ---
Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "  ✔  Consolidação concluída." -ForegroundColor Green
} else {
    Write-Host "  ✖  Ocorreu um erro (código $ExitCode)." -ForegroundColor Red
}
Write-Host ""
