[CmdletBinding()]
param(
    [switch]$WithHttps
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$composeEnv = Join-Path $root '.env.compose'
$composeFile = Join-Path $root 'docker-compose.yml'

if (-not (Test-Path -LiteralPath $composeEnv)) { throw '未找到 .env.compose；请从 .env.compose.example 创建并填写本机配置。' }
if (-not (Test-Path -LiteralPath $composeFile)) { throw '未找到 docker-compose.yml。' }

$dockerCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCompose) {
    & $dockerCompose.Source --env-file $composeEnv -f $composeFile up -d mysql redis
} elseif ($docker) {
    & $docker.Source compose --env-file $composeEnv -f $composeFile up -d mysql redis
} else {
    throw '未找到 Docker Compose。请先安装并启动 Docker Desktop。'
}
if ($LASTEXITCODE -ne 0) { throw "MySQL/Redis 启动失败（退出码 $LASTEXITCODE）。" }

if (-not $docker) { $docker = Get-Command docker -ErrorAction Stop }
function Wait-ContainerHealthy([string]$ContainerName) {
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $state = (& $docker.Source inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $ContainerName 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $state -in @('healthy', 'running')) { return }
        if ($state -in @('unhealthy', 'exited', 'dead')) { throw "$ContainerName 状态异常：$state" }
        Start-Sleep -Seconds 2
    } until ((Get-Date) -ge $deadline)
    throw "等待 $ContainerName 就绪超时。"
}
Wait-ContainerHealthy 'meetingmind-mysql'
Wait-ContainerHealthy 'meetingmind-redis'

$venv = (& (Join-Path $root 'scripts\resolve_runtime_venv.ps1') -RequireAudio | Select-Object -Last 1).Trim()
$alembic = Join-Path $venv 'Scripts\alembic.exe'
$env:PYTHONPATH = Join-Path $root 'backend'
& $alembic -c (Join-Path $root 'backend\alembic.ini') upgrade head
if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败（退出码 $LASTEXITCODE）。" }

& (Join-Path $root 'scripts\start_api_background.ps1')
if ($LASTEXITCODE -ne 0) { throw "API 启动失败（退出码 $LASTEXITCODE）。" }
& (Join-Path $root 'scripts\start_rq_worker_background.ps1')
if ($LASTEXITCODE -ne 0) { throw "RQ Worker 启动失败（退出码 $LASTEXITCODE）。" }

if ($WithHttps) {
    & (Join-Path $root 'scripts\start_secure_edge.ps1')
    if ($LASTEXITCODE -ne 0) { throw "HTTPS 前端边界启动失败（退出码 $LASTEXITCODE）。" }
    Write-Host '完整本机服务已就绪：https://localhost:8443' -ForegroundColor Green
} else {
    Write-Host '后端、队列和音频 Worker 已就绪。' -ForegroundColor Green
    Write-Host '开发前端请在新的 PowerShell 执行：cd D:\MeetingMind\frontend; npm run dev'
    Write-Host '然后访问：http://localhost:5173'
}
