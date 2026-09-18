param(
    [string]$Queue = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stderr = Join-Path $logs "rq-host.stderr.log"
$maxErrorLogBytes = 10MB
if ((Test-Path -LiteralPath $stderr) -and (Get-Item -LiteralPath $stderr).Length -ge $maxErrorLogBytes) {
    for ($index = 4; $index -ge 1; $index--) {
        $source = if ($index -eq 1) { $stderr } else { "$stderr.$($index - 1)" }
        $target = "$stderr.$index"
        if (Test-Path -LiteralPath $source) { Move-Item -LiteralPath $source -Destination $target -Force }
    }
}

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
    -RedirectStandardOutput "NUL" -RedirectStandardError $stderr -PassThru
Write-Host "MeetingMind RQ Worker 已作为后台进程启动（启动器 PID: $($process.Id)）。"
Write-Host "结构化轮转日志：$(Join-Path $logs 'worker.jsonl')"
Write-Host "宿主错误日志：$stderr"
