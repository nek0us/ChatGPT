param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory,
    [int]$RestartDelaySeconds = 5
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $WorkingDirectory

while ($true) {
    & $PythonExecutable -m ChatGPTWeb.core_server --env-file $EnvFile
    $exitCode = $LASTEXITCODE
    Write-Host "ChatGPTWeb core exited with code $exitCode; restarting in $RestartDelaySeconds seconds."
    Start-Sleep -Seconds $RestartDelaySeconds
}
