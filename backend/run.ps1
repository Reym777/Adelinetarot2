# AdelineTarot - lanzar el backend en local (PowerShell)
# Uso :  .\run.ps1
$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No se encontro el venv en $venvPython - usando 'python' del PATH." -ForegroundColor Yellow
    $venvPython = "python"
}

# Acceso desde el telefono (misma red Wi-Fi): escuchamos en todas las interfaces
# y permitimos cualquier Host (solo desarrollo). En produccion, fija
# ADELINE_ALLOWED_HOSTS con tu dominio real.
$env:ADELINE_ALLOWED_HOSTS = "*"

# Muestra la URL a abrir en el telefono (IP del PC en la red local).
$lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host ""
Write-Host "  AdelineTarot arrancando..." -ForegroundColor Cyan
Write-Host "  En este PC     : http://127.0.0.1:8000" -ForegroundColor Green
if ($lan) {
    $lanUrl = "http://" + $lan + ":8000"
    Write-Host "  En el telefono : $lanUrl   (misma red Wi-Fi)" -ForegroundColor Green
}
Write-Host ""

Push-Location $PSScriptRoot
try {
    & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
}
finally {
    Pop-Location
}
