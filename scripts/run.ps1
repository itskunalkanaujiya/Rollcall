# Starts backend and frontend in two windows, then opens the browser.
$s = $PSScriptRoot
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',(Join-Path $s 'start-backend.ps1')
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',(Join-Path $s 'start-frontend.ps1')
Start-Sleep -Seconds 8
Start-Process 'http://localhost:5173'
Write-Host 'Backend: http://127.0.0.1:8000/docs   App: http://localhost:5173'
