param(
    [string]$Queue = "",
    [ValidateSet("auto", "simple", "spawn")]
    [string]$WorkerClass = "auto"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = (& (Join-Path $root 'scripts\resolve_runtime_venv.ps1') -RequireAudio | Select-Object -Last 1).Trim()
$python = Join-Path $venv "Scripts\python.exe"
$rq = Join-Path $venv "Scripts\rq.exe"
if (-not (Test-Path $python)) { throw "未找到后端虚拟环境：$python" }
if (-not (Test-Path $rq)) { throw "未找到 RQ 命令：$rq；请先执行 uv sync --frozen --group dev" }

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
& $python -c "import logging; from app.config import Settings; from app.observability import configure_logging; s=Settings.from_env(); configure_logging(s.log_level, log_file=s.data_dir / 'logs' / 'worker.jsonl', max_bytes=s.log_max_bytes, backup_count=s.log_backup_count); logging.getLogger('meetingmind.worker').info('rq_worker_host_starting')"
if ($LASTEXITCODE -ne 0) { throw '无法初始化 Worker 结构化日志' }
Write-Host "Starting RQ worker: queue=$Queue worker_class=$workerClassPath redis=configured"
& $rq worker --url $redisUrl --worker-class $workerClassPath $Queue
