[CmdletBinding()]
param(
    [int]$HttpsPort = 0
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$composeEnv = Join-Path $root '.env.compose'

$dockerCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCompose -and -not $docker) { throw '未找到 Docker CLI' }
function Invoke-Compose([string[]]$ComposeArgs) {
    if ($dockerCompose) { & $dockerCompose.Source @ComposeArgs }
    else { & $docker.Source compose @ComposeArgs }
}
if (-not (Test-Path $composeEnv)) { throw '未找到 .env.compose；请先从 .env.compose.example 创建本地配置' }

Push-Location $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端生产构建失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}

if ($HttpsPort -le 0) {
    $HttpsPort = 8443
    foreach ($line in Get-Content $composeEnv -Encoding utf8) {
        if ($line.Trim() -match '^EDGE_HTTPS_PORT=(\d+)$') { $HttpsPort = [int]$Matches[1] }
    }
}

Invoke-Compose @('--env-file', $composeEnv, '--profile', 'edge', 'up', '-d', 'caddy')
if ($LASTEXITCODE -ne 0) { throw "Caddy 启动失败（退出码 $LASTEXITCODE）" }

$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 2
    & curl.exe -kfsS "https://localhost:$HttpsPort/api/v1/health" -o NUL 2>$null
    $ready = $LASTEXITCODE -eq 0
} until ($ready -or (Get-Date) -gt $deadline)

if (-not $ready) {
    Invoke-Compose @('--env-file', $composeEnv, '--profile', 'edge', 'logs', '--tail', '100', 'caddy')
    throw "HTTPS 边界未在 60 秒内就绪：https://localhost:$HttpsPort"
}

Write-Host "MeetingMind 本地 HTTPS 边界已就绪：https://localhost:$HttpsPort" -ForegroundColor Green
Write-Host '本地证书由 Caddy 内部 CA 签发；未安装根证书时浏览器会显示不受信任提示。'
