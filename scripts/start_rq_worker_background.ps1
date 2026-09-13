param(
    [string]$Queue = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stdout = Join-Path $logs "rq-worker.stdout.log"
$stderr = Join-Path $logs "rq-worker.stderr.log"

# Do not start duplicates: Redis can register old worker keys briefly, so use
# the real Windows process list as the authority.
$running = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match '(?i)rq\.exe.*worker.*meetingmind'
}
if ($running) {
    $ids = ($running | ForEach-Object ProcessId) -join ", "
    Write-Host "MeetingMind RQ Worker 已在运行（PID: $ids）。"
    exit 0
}

$args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\start_rq_worker.ps1"))
if ($Queue) { $args += @("-Queue", $Queue) }
$process = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Write-Host "MeetingMind RQ Worker 已作为后台进程启动（启动器 PID: $($process.Id)）。"
Write-Host "日志：$stdout"
Write-Host "错误日志：$stderr"
