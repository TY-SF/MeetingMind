param(
    [string]$Queue = "",
    [ValidateSet("auto", "simple", "spawn")]
    [string]$WorkerClass = "auto"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$rq = Join-Path $root "backend\.venv\Scripts\rq.exe"
if (-not (Test-Path $python)) { throw "未找到后端虚拟环境：$python" }
if (-not (Test-Path $rq)) { throw "未找到 RQ 命令：$rq；请先安装 backend/requirements.txt" }

# RQ 2.6.x 的 SpawnWorker 在 Windows 会调用 os.wait4，而 Windows Python
# 不提供该 API，导致 Worker 取到任务后立即退出。Windows 默认使用
# SimpleWorker（不 fork，任务仍在独立的 RQ Worker 进程中执行）；在
# Linux/macOS 上继续使用 SpawnWorker。可通过 -WorkerClass 显式覆盖。
# 需要脱离当前终端常驻时，执行 start_rq_worker_background.ps1。
$env:PYTHONPATH = Join-Path $root "backend"
if (-not $Queue) {
    $Queue = (& $python -c "from app.config import Settings; print(Settings.from_env().rq_queue_name)").Trim()
}
$redisUrl = (& $python -c "from app.config import Settings; print(Settings.from_env().redis_url)").Trim()
if ($WorkerClass -eq "auto") {
    $WorkerClass = if ($env:OS -eq "Windows_NT") { "simple" } else { "spawn" }
}
$workerClassPath = if ($WorkerClass -eq "simple") { "rq.worker.SimpleWorker" } else { "rq.worker.SpawnWorker" }
Write-Host "Starting RQ worker: queue=$Queue worker_class=$workerClassPath redis=$redisUrl"
& $rq worker --url $redisUrl --worker-class $workerClassPath $Queue
