param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory,
    [string]$TaskName = "ChatGPTWeb Core",
    [switch]$DoNotStart
)

$ErrorActionPreference = "Stop"
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$guardian = Join-Path $scriptDirectory "chatgptweb-core-guardian.ps1"
foreach ($path in @($PythonExecutable, $EnvFile, $WorkingDirectory, $guardian)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path does not exist: $path"
    }
}

function Quote-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Quote-TaskArgument $guardian),
    "-PythonExecutable", (Quote-TaskArgument (Resolve-Path -LiteralPath $PythonExecutable)),
    "-EnvFile", (Quote-TaskArgument (Resolve-Path -LiteralPath $EnvFile)),
    "-WorkingDirectory", (Quote-TaskArgument (Resolve-Path -LiteralPath $WorkingDirectory))
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'. It starts when this Windows user logs on."
Write-Host "Status: Get-ScheduledTask -TaskName '$TaskName'"
if (-not $DoNotStart) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started '$TaskName'."
}
