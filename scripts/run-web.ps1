# Run the predictor web app (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== Soccer Predictor Web App ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example - add your CURSOR_API_KEY" -ForegroundColor Yellow
    }
}

Write-Host "Installing Python deps..."
pip install -e ".[web]" -q 2>$null
if ($LASTEXITCODE -ne 0) {
    pip install cursor-sdk fastapi uvicorn pydantic python-dotenv aiofiles requests beautifulsoup4 -q
}

if (Test-Path "webapp\package.json") {
    if (-not (Test-Path "webapp\node_modules")) {
        Write-Host "Installing frontend deps..."
        Push-Location webapp
        npm install
        Pop-Location
    }
    Write-Host "Building frontend..."
    Push-Location webapp
    npm run build
    Pop-Location
}

$url = "http://127.0.0.1:8765"
Write-Host "Starting server at $url"
Start-Process $url
python -m predictor.web.app
