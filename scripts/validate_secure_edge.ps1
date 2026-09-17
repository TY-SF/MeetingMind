$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$composeEnv = Join-Path $root '.env.compose'
$localCaddyfile = Join-Path $root 'deploy\Caddyfile.local'
$productionCaddyfile = Join-Path $root 'deploy\Caddyfile.production.example'

$dockerCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCompose -and -not $docker) { throw '未找到 Docker CLI' }
function Invoke-Compose([string[]]$ComposeArgs) {
    if ($dockerCompose) { & $dockerCompose.Source @ComposeArgs }
    else { & $docker.Source compose @ComposeArgs }
}

Invoke-Compose @('--env-file', $composeEnv, '--profile', 'edge', 'config', '--quiet')
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose edge 配置校验失败' }

foreach ($file in @($localCaddyfile, $productionCaddyfile)) {
    if (-not (Test-Path $file)) { throw "缺少 Caddy 配置：$file" }
    & docker run --rm --volume "${file}:/etc/caddy/Caddyfile:ro" caddy:2.10.2-alpine `
        caddy validate --config /etc/caddy/Caddyfile
    if ($LASTEXITCODE -ne 0) { throw "Caddy 配置校验失败：$file" }
}

$localText = Get-Content $localCaddyfile -Raw -Encoding utf8
$productionText = Get-Content $productionCaddyfile -Raw -Encoding utf8
if ($localText -notmatch 'tls internal') { throw '本地 Caddy 配置必须显式使用内部 CA' }
if ($productionText -match 'tls internal') { throw '生产 Caddy 示例不能使用内部 CA' }
if ($productionText -notmatch 'Strict-Transport-Security') { throw '生产 Caddy 示例缺少 HSTS' }
if ($productionText -notmatch '127\.0\.0\.1:8000') { throw '生产 Caddy 示例必须默认代理到回环 API' }

Write-Host '[PASS] HTTPS/Caddy 本地与生产配置校验通过。' -ForegroundColor Green
