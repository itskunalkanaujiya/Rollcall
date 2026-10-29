# Starts the API on http://127.0.0.1:8000  (Swagger UI: /docs)
$ErrorActionPreference = 'Stop'
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
Set-Location $backend
& (Join-Path $backend '.venv\Scripts\python.exe') -m uvicorn app.main:app --host 127.0.0.1 --port 8000
