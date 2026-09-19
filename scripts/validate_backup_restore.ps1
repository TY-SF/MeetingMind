[CmdletBinding()]
param(
    [string]$DataDir,
    [string]$OutputPath,
    [string]$Container = 'meetingmind-mysql',
    [string]$Database = 'meetingmind',
    [switch]$KeepRestoreDir,
    [switch]$RemoveArchive
)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $root 'data'
}
$venv = (& (Join-Path $root 'scripts\resolve_runtime_venv.ps1') | Select-Object -Last 1).Trim()
$python = Join-Path $venv 'Scripts\python.exe'
$cli = Join-Path $root 'scripts\backup_restore.py'
if (-not (Test-Path -LiteralPath $python)) { throw "未找到后端 Python：$python" }
if (-not (Test-Path -LiteralPath $cli)) { throw "未找到备份工具：$cli" }

$dataRoot = [System.IO.Path]::GetFullPath($DataDir)
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
if (-not $OutputPath) {
    $OutputPath = Join-Path $dataRoot "backups\meetingmind-$stamp.zip"
}
$archive = [System.IO.Path]::GetFullPath($OutputPath)
$restoreRoot = [System.IO.Path]::GetFullPath((Join-Path $dataRoot "restore-drill"))
$restoreTarget = Join-Path $restoreRoot $stamp
$dbName = "meetingmind_restore_${stamp}_$PID" -replace '[^A-Za-z0-9_]', '_'

# The only path this script may remove is a newly-created child of restore-drill.
$restorePrefix = $restoreRoot.TrimEnd('\') + '\'
if (-not $restoreTarget.StartsWith($restorePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '恢复演练目标不在受控 restore-drill 目录内'
}
if ($restoreTarget -eq $dataRoot -or $restoreTarget -eq $root) { throw '拒绝使用项目或数据根目录作为恢复演练目标' }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $archive) | Out-Null
try {
    Write-Host '创建备份归档（不打印数据库密码或业务内容）...' -ForegroundColor Cyan
    & $python $cli backup --data-dir $dataRoot --output $archive --database $Database --container $Container
    if ($LASTEXITCODE -ne 0) { throw '备份创建失败' }

    Write-Host '验证归档 manifest、SHA-256 和路径边界...' -ForegroundColor Cyan
    & $python $cli verify $archive
    if ($LASTEXITCODE -ne 0) { throw '备份验证失败' }

    Write-Host '恢复到隔离目录和临时隔离数据库...' -ForegroundColor Cyan
    & $python $cli restore $archive --target-dir $restoreTarget --container $Container --isolated-database $dbName
    if ($LASTEXITCODE -ne 0) { throw '隔离恢复演练失败' }
    Write-Host "备份/恢复演练通过；归档保留在：$archive" -ForegroundColor Green
} finally {
    if (-not $KeepRestoreDir -and (Test-Path -LiteralPath $restoreTarget)) {
        Remove-Item -LiteralPath $restoreTarget -Recurse -Force
    }
    if ($RemoveArchive -and (Test-Path -LiteralPath $archive)) {
        Remove-Item -LiteralPath $archive -Force
    }
}
