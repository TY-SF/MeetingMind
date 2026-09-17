$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$composeEnv = Join-Path $root '.env.compose'

$dockerCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCompose -and -not $docker) { throw '未找到 Docker CLI' }
function Invoke-Compose([string[]]$ComposeArgs) {
    if ($dockerCompose) { & $dockerCompose.Source @ComposeArgs }
    else { & $docker.Source compose @ComposeArgs }
}
Invoke-Compose @('--env-file', $composeEnv, '--profile', 'edge', 'stop', 'caddy')
if ($LASTEXITCODE -ne 0) { throw "停止 Caddy 失败（退出码 $LASTEXITCODE）" }
Write-Host 'MeetingMind 本地 HTTPS 边界已停止。'
