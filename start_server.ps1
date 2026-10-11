# Script para iniciar JARVIS en Windows PowerShell
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   Iniciando JARVIS AI Assistant Backend   " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[!] Archivo .env creado a partir de .env.example. Configura tu GEMINI_API_KEY." -ForegroundColor Yellow
}

# Verificar clave
$envContent = Get-Content ".env" -Raw
if ($envContent -match "GEMINI_API_KEY=\s*$" -or $envContent -match "GEMINI_API_KEY=\s*tu_") {
    Write-Host "[ADVERTENCIA] GEMINI_API_KEY parece estar vacia en tu archivo .env." -ForegroundColor Yellow
    Write-Host "Obten una clave gratis en: https://aistudio.google.com/" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "[+] Iniciando FastAPI en http://localhost:8000" -ForegroundColor Green
Write-Host "[+] Documentacion interactiva disponible en: http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""

& ".\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
