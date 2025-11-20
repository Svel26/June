param()

$Root = Split-Path -Parent $PSScriptRoot
$AgentDir = Join-Path $Root "agent-server"

Write-Host "Creating venv in $AgentDir\venv"
python -m venv "$AgentDir\venv"

$Pip = Join-Path $AgentDir "venv\\Scripts\\pip.exe"

if (-Not (Test-Path $Pip)) {
    Write-Error "pip not found in venv. Ensure Python is available on PATH."
    exit 1
}

Write-Host "Upgrading pip and installing requirements..."
& $Pip install --upgrade pip
$Requirements = Join-Path $AgentDir "requirements.txt"
if (Test-Path $Requirements) {
    & $Pip install -r $Requirements
} else {
    Write-Error "requirements.txt not found at $Requirements"
    exit 1
}

Write-Host "Done. To run the agent-server use:"
Write-Host "`t$AgentDir\\venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"