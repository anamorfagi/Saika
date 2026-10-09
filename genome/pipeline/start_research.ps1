$ErrorActionPreference = 'Stop'
$researchRoot = Split-Path $PSScriptRoot -Parent
$researchWorker = Join-Path $PSScriptRoot 'research_server.py'
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8770/health' -TimeoutSec 2
    if ($health.service -eq 'genome-research') { return }
    throw 'Port 8770 belongs to another service'
} catch {
    if ($_.Exception.Message -eq 'Port 8770 belongs to another service') { throw }
}
$researchPython = @(
    (Join-Path $researchRoot '..\.venv\Scripts\python.exe'),
    (Join-Path $researchRoot '..\..\.venv\Scripts\python.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $researchPython) { $researchPython = (Get-Command python -ErrorAction Stop).Source }
Start-Process -FilePath $researchPython -ArgumentList @('-u', ('"' + $researchWorker + '"')) -WorkingDirectory $researchRoot -WindowStyle Hidden
