[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://localhost:8443',
    [switch]$TrustLocalCaddyCA,
    [double]$BackupMaxAgeHours = 26,
    [double]$DiskWarningFreePercent = 15,
    [double]$DiskCriticalFreePercent = 5
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = (& (Join-Path $root 'scripts\resolve_runtime_venv.ps1') | Select-Object -Last 1).Trim()
$python = Join-Path $venv 'Scripts\python.exe'
$script = Join-Path $root 'scripts\check_operations.py'
if (-not (Test-Path -LiteralPath $python)) { throw "未找到后端 Python：$python" }
$args = @(
    $script,
    '--base-url', $BaseUrl,
    '--backup-max-age-hours', $BackupMaxAgeHours,
    '--disk-warning-free-percent', $DiskWarningFreePercent,
    '--disk-critical-free-percent', $DiskCriticalFreePercent
)
if ($TrustLocalCaddyCA) { $args += '--allow-insecure-localhost' }
& $python @args
exit $LASTEXITCODE
