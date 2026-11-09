# Starts the whole platform on http://127.0.0.1:8000 (API + built UI). Run from the project root.
#   .\start.ps1            build UI if needed, then start
#   .\start.ps1 -Dev       API on :8000 + Vite dev server on :5173 (hot reload)
param([switch]$Dev)

$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating backend virtualenv..."
    python -m venv (Join-Path $root "backend\.venv")
    & $py -m pip install -q -r (Join-Path $root "backend\requirements.txt")
}

$hasNode = [bool](Get-Command npm -ErrorAction SilentlyContinue)
if ($hasNode) {
    Push-Location (Join-Path $root "frontend")
    if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
    if ($Dev) {
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; npm run dev"
    } elseif (-not (Test-Path "dist\index.html")) {
        npm run build
    }
    Pop-Location
} else {
    Write-Warning "Node.js not found - starting the API only (Swagger docs at /docs)."
}

Set-Location (Join-Path $root "backend")
Write-Host "Open http://127.0.0.1:8000  (API docs: /docs)"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
