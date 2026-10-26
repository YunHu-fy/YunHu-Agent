param([int]$Port = 8686)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m android_agent --port $Port --open-browser
exit $LASTEXITCODE
