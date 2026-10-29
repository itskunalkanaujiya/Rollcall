# Creates the first (or another) administrator. Prompts for username and password; nothing is hard-coded.
$ErrorActionPreference = 'Stop'
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
Set-Location $backend
& (Join-Path $backend '.venv\Scripts\python.exe') -m app.cli create-admin @args
