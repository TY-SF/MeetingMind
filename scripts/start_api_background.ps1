[CmdletBinding()]
param(
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = if (Test-Path (Join-Path $root '.venv\Scripts\python.exe')) { Join-Path $root '.venv' } else { Join-Path $root 'backend\.venv' }
$python = Join-Path $venv 'Scripts\python.exe'
$logs = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if (-not (Test-Path -LiteralPath $python)) { throw "未找到后端 Python：$python" }

$running = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match '(?i)uvicorn.*app\.main:app' -and $_.CommandLine -match "--port\s+$Port(?:\s|$)"
}
if ($running) {
    $ids = ($running | ForEach-Object ProcessId) -join ', '
    Write-Host "MeetingMind API 已在运行（PID: $ids）。"
    exit 0
}

$stderr = Join-Path $logs 'api-host.stderr.log'
$maxErrorLogBytes = 10MB
if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -ge $maxErrorLogBytes) {
    for ($index = 4; $index -ge 1; $index--) {
        $source = if ($index -eq 1) { $stderr } else { "$stderr.$($index - 1)" }
        $target = "$stderr.$index"
        if (Test-Path -LiteralPath $source) { Move-Item -LiteralPath $source -Destination $target -Force }
    }
}

$args = @(
    '-m', 'uvicorn', 'app.main:app',
    '--app-dir', (Join-Path $root 'backend'),
    '--host', $HostAddress,
    '--port', $Port,
    '--no-access-log',
    '--log-level', 'warning'
)
$process = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput 'NUL' -RedirectStandardError $stderr -PassThru
Start-Sleep -Seconds 2
try {
    $health = Invoke-RestMethod "http://$HostAddress`:$Port/api/v1/health" -TimeoutSec 5
    if ($health.status -ne 'ok') { throw '健康检查未返回 ok' }
} catch {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    throw "MeetingMind API 启动后健康检查失败；查看 $stderr"
}
Write-Host "MeetingMind API 已在后台运行（PID: $($process.Id)）。"
Write-Host "结构化轮转日志：$(Join-Path $logs 'api.jsonl')"
Write-Host "宿主错误日志：$stderr"
