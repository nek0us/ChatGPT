param([string]$TaskName = "ChatGPTWeb Core")

$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task '$TaskName'. Existing core data was left untouched."
