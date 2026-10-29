# Runs every automated check: backend pytest, frontend type-check, unit tests and production build.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'backend');  & .\.venv\Scripts\python.exe -m pytest -v
Set-Location (Join-Path $root 'frontend'); npm run typecheck; npm test; npm run build
