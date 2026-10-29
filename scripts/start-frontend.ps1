# Starts the web app on http://localhost:5173 (proxies /api to the backend on :8000)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
npm run dev
