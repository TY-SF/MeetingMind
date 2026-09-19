[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipLiveServer,
    [switch]$SkipInfrastructure,
    [switch]$SkipBackupRestore,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = if (Test-Path (Join-Path $root '.venv\Scripts\python.exe')) { Join-Path $root '.venv' } else { Join-Path $root 'backend\.venv' }
$python = Join-Path $venv 'Scripts\python.exe'
$alembic = Join-Path $venv 'Scripts\alembic.exe'
$envFile = Join-Path $root 'backend\.env\meetingmind.env'
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$checks = [System.Collections.Generic.List[object]]::new()
$testEnvironmentNames = @(
    'MEETINGMIND_ENV_FILE',
    'MEETINGMIND_INFRA_ENV_FILE',
    'MEETINGMIND_DATABASE_URL',
    'MYSQL_HOST',
    'MYSQL_PORT',
    'MYSQL_DATABASE',
    'MYSQL_USER',
    'MYSQL_PASSWORD',
    'MEETINGMIND_API_TOKEN'
)

function Write-Pass([string]$message) { Write-Host "[PASS] $message" -ForegroundColor Green; $script:checks.Add([pscustomobject]@{ name = $message; status = 'pass' }) }
function Write-Warn([string]$message) { Write-Host "[WARN] $message" -ForegroundColor Yellow; $script:warnings.Add($message); $script:checks.Add([pscustomobject]@{ name = $message; status = 'warning' }) }
function Write-Fail([string]$message) { Write-Host "[FAIL] $message" -ForegroundColor Red; $script:failures.Add($message); $script:checks.Add([pscustomobject]@{ name = $message; status = 'fail' }) }
function Invoke-External([string]$name, [scriptblock]$action) {
    try {
        & $action
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "退出码 $LASTEXITCODE" }
        Write-Pass $name
    } catch {
        Write-Fail "$name：$($_.Exception.Message)"
    }
}
function Invoke-IsolatedBackendCheck([string]$name, [scriptblock]$action) {
    $saved = @{}
    foreach ($nameToClear in $testEnvironmentNames) {
        $saved[$nameToClear] = [Environment]::GetEnvironmentVariable($nameToClear, 'Process')
        [Environment]::SetEnvironmentVariable($nameToClear, $null, 'Process')
    }
    $isolatedEnvFile = Join-Path $env:TEMP 'meetingmind-isolated-test-missing.env'
    [Environment]::SetEnvironmentVariable('MEETINGMIND_ENV_FILE', $isolatedEnvFile, 'Process')
    try {
        Invoke-External $name $action
    } finally {
        foreach ($nameToRestore in $testEnvironmentNames) {
            [Environment]::SetEnvironmentVariable($nameToRestore, $saved[$nameToRestore], 'Process')
        }
    }
}
function Invoke-NpmAudit {
    $output = @(& npm audit --omit=dev --audit-level=high 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-Pass '前端生产依赖安全审计（高危阈值）'
        return
    }
    $text = ($output | Out-String).Trim()
    if ($text -match '(?i)audit endpoint|ECONNRESET|ETIMEDOUT|ENETUNREACH|EAI_AGAIN|network|returned an error') {
        Write-Warn '前端生产依赖安全审计未完成：npm registry 当前不可达；未将网络故障误判为依赖漏洞'
        return
    }
    throw "npm audit 发现问题或执行失败（退出码 $LASTEXITCODE）"
}

Write-Host "MeetingMind 发布前完整检查（$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')）" -ForegroundColor Cyan
Write-Host "工作目录：$root"

if (-not $SkipInfrastructure) {
    try {
        $dockerCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if (-not $dockerCompose -and -not $docker) { throw '未找到 Docker CLI；如当前环境不运行 Docker，请使用 -SkipInfrastructure 明确跳过' }
        $composeFile = Join-Path $root 'docker-compose.yml'
        $composeEnvFile = Join-Path $root '.env.compose'
        if (-not (Test-Path $composeFile)) { throw '未找到 docker-compose.yml' }
        if (-not (Test-Path $composeEnvFile)) { throw '未找到 .env.compose；请从 .env.compose.example 创建并填写本地密码' }
        if ($dockerCompose) {
            Invoke-External 'Docker Compose 配置校验' { & $dockerCompose.Source --env-file $composeEnvFile -f $composeFile config --quiet }
        } else {
            $composeVersion = (& $docker.Source compose version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 插件不可用，且未找到 docker-compose 独立命令' }
            Invoke-External 'Docker Compose 配置校验' { & $docker.Source compose --env-file $composeEnvFile -f $composeFile config --quiet }
        }
        Invoke-External 'HTTPS/Caddy 边界配置校验' { & (Join-Path $root 'scripts\validate_secure_edge.ps1') }
        if (-not $SkipBackupRestore) {
            Invoke-External 'MySQL 与会议文件一致性备份及隔离恢复演练' {
                & (Join-Path $root 'scripts\validate_backup_restore.ps1') -RemoveArchive
            }
        } else {
            Write-Warn '已显式跳过备份与隔离恢复演练（-SkipBackupRestore）'
        }
    } catch {
        Write-Fail "Docker Compose 检查：$($_.Exception.Message)"
    }
} else {
    Write-Warn '已跳过 Docker Compose 配置检查（-SkipInfrastructure）'; Write-Warn '基础设施已跳过，因此未执行备份与隔离恢复演练'
}

if (-not (Test-Path $python)) { throw "未找到后端虚拟环境：$python" }
if (-not (Test-Path $alembic)) { throw "未找到 Alembic：$alembic" }

# Never echo values from the secret file. Only validate that required keys are set.
try {
    if (-not (Test-Path $envFile)) { throw "未找到本地配置文件 backend/.env/meetingmind.env" }
    $values = @{}
    foreach ($line in Get-Content $envFile -Encoding utf8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $parts = $trimmed.Split('=', 2)
        $values[$parts[0].Trim()] = $parts[1].Trim().Trim('"').Trim("'")
    }
    $required = @('OPENAI_API_KEY', 'HF_TOKEN')
    foreach ($key in $required) {
        if (-not $values.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($values[$key]) -or $values[$key] -match '请填写|在本机填写|change-me') {
            throw "配置字段 $key 未填写或仍为模板占位符"
        }
    }
    $hasExplicitUrl = $values.ContainsKey('MEETINGMIND_DATABASE_URL') -and $values['MEETINGMIND_DATABASE_URL'] -and $values['MEETINGMIND_DATABASE_URL'] -notmatch '请填写|change-me'
    $hasMysqlFields = @('MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD') | ForEach-Object {
        $values.ContainsKey($_) -and $values[$_] -and $values[$_] -notmatch '请填写|change-me'
    }
    if (-not $hasExplicitUrl -and ($hasMysqlFields -contains $false)) { throw '数据库连接字段未完整填写' }
    if (-not $values.ContainsKey('MEETINGMIND_API_TOKEN') -or $values['MEETINGMIND_API_TOKEN'].Length -lt 32) {
        throw 'MEETINGMIND_API_TOKEN 未配置或少于 32 个字符'
    }
    $apiHeaders = @{ Authorization = "Bearer $($values['MEETINGMIND_API_TOKEN'])" }
    $edgeHttpsPort = 8443
    $composeEnvPath = Join-Path $root '.env.compose'
    if (Test-Path $composeEnvPath) {
        foreach ($line in Get-Content $composeEnvPath -Encoding utf8) {
            if ($line.Trim() -match '^EDGE_HTTPS_PORT=(\d+)$') { $edgeHttpsPort = [int]$Matches[1] }
        }
    }
    Write-Pass '本地配置字段和部署级访问令牌存在（未输出敏感值）'
} catch {
    Write-Fail "本地配置检查：$($_.Exception.Message)"
}

try {
    $ignore = Get-Content (Join-Path $root '.gitignore') -Raw -Encoding utf8
    if ($ignore -notmatch 'backend/\.env/' -or $ignore -notmatch '\*\.mp3') { throw '.gitignore 未覆盖本地密钥目录或音频文件' }
    Write-Pass '.gitignore 覆盖密钥目录和本地音频'
} catch {
    Write-Fail ".gitignore 检查：$($_.Exception.Message)"
}

$env:PYTHONPATH = Join-Path $root 'backend'
Invoke-External 'Git 候选文件安全审查' { & $python (Join-Path $root 'scripts\repository_audit.py') }
Invoke-External 'Git 完整历史敏感信息审查' { & $python (Join-Path $root 'scripts\git_history_audit.py') }
Invoke-External 'Alembic 迁移升级到 head' { & $alembic -c (Join-Path $root 'backend\alembic.ini') upgrade head }
try {
    $heads = (& $alembic -c (Join-Path $root 'backend\alembic.ini') heads 2>&1 | Out-String).Trim()
    $current = (& $alembic -c (Join-Path $root 'backend\alembic.ini') current 2>&1 | Out-String).Trim()
    $headRevision = ($heads -split '\r?\n' | Where-Object { $_ -match '^\w+' } | Select-Object -First 1).Split(' ')[0]
    if (-not $headRevision -or $current -notmatch [regex]::Escape($headRevision)) { throw "当前迁移未处于 head（head=$headRevision）" }
    Write-Pass "数据库迁移位于 head：$headRevision"
} catch {
    Write-Fail "迁移版本检查：$($_.Exception.Message)"
}

if (-not $SkipLiveServer) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 10
        $ready = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 10
        if ($health.status -ne 'ok' -or $ready.status -ne 'ready') { throw '健康检查未返回 ok/ready' }
        Write-Pass '运行中 API 与数据库健康检查'
    } catch {
        Write-Fail "运行中服务健康检查：$($_.Exception.Message)"
    }

    try {
        $queue = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health/queue' -Headers $apiHeaders -TimeoutSec 10
        if ($queue.redis -ne 'ok') { throw "Redis 状态异常：$($queue.redis)" }
        if (-not $queue.worker_online) { throw 'RQ Worker 未在线；发布前不能接受会被伪装为已排队的任务' }
        if ($queue.status -ne 'ready') { throw "队列状态异常：$($queue.status)" }
        Write-Pass "Redis/RQ Worker 健康检查（Worker=$($queue.worker_count)，队列=$($queue.queue_length)）"
    } catch {
        Write-Fail "Redis/RQ Worker 健康检查：$($_.Exception.Message)"
    }

    try {
        $edgeHeadersPath = Join-Path $env:TEMP 'meetingmind-edge-headers.txt'
        & curl.exe -kfsS -D $edgeHeadersPath -o NUL "https://localhost:$edgeHttpsPort/api/v1/health"
        if ($LASTEXITCODE -ne 0) { throw "HTTPS 健康检查失败（退出码 $LASTEXITCODE）" }
        $edgeHeaders = Get-Content $edgeHeadersPath -Raw -Encoding utf8
        if ($edgeHeaders -notmatch '(?im)^X-Content-Type-Options:\s*nosniff') { throw 'HTTPS 响应缺少 nosniff' }
        if ($edgeHeaders -notmatch '(?im)^Content-Security-Policy:') { throw 'HTTPS 响应缺少 CSP' }
        & curl.exe -kfsS -o NUL -H "Authorization: $($apiHeaders.Authorization)" "https://localhost:$edgeHttpsPort/api/v1/meetings"
        if ($LASTEXITCODE -ne 0) { throw "HTTPS 受保护接口检查失败（退出码 $LASTEXITCODE）" }
        Write-Pass "本地 HTTPS 反向代理与安全响应头（端口 $edgeHttpsPort）"
    } catch {
        Write-Fail "HTTPS 反向代理检查：$($_.Exception.Message)"
    }

    try {
        $spec = Invoke-RestMethod 'http://127.0.0.1:8000/openapi.json' -TimeoutSec 10
        $requiredPaths = @(
            '/api/v1/meetings',
            '/api/v1/jobs/{job_id}',
            '/api/v1/jobs/{job_id}/retry',
            '/api/v1/meetings/{meeting_id}/analysis',
            '/api/v1/meetings/{meeting_id}/speakers',
            '/api/v1/meetings/{meeting_id}/exports/calendar'
        )
        foreach ($path in $requiredPaths) {
            if (-not $spec.paths.PSObject.Properties.Name.Contains($path)) { throw "OpenAPI 缺少路径 $path" }
        }
        $jobProperties = $spec.components.schemas.ProcessingJob.properties.PSObject.Properties.Name
        foreach ($property in @('diarization_status', 'speaker_count', 'stage_events')) {
            if ($jobProperties -notcontains $property) { throw "OpenAPI ProcessingJob 缺少字段 $property" }
        }

        $uploadSchemaRef = $spec.paths.'/api/v1/meetings'.post.requestBody.content.'multipart/form-data'.schema.'$ref'
        $uploadSchemaName = ($uploadSchemaRef -split '/')[-1]
        $uploadProperties = $spec.components.schemas.$uploadSchemaName.properties.PSObject.Properties.Name
        if ($uploadProperties -notcontains 'data_processing_confirmed') { throw 'OpenAPI 上传契约缺少 data_processing_confirmed' }

        $analysisSchemaRef = $spec.paths.'/api/v1/meetings/{meeting_id}/analysis'.post.requestBody.content.'application/json'.schema.'$ref'
        $analysisSchemaName = ($analysisSchemaRef -split '/')[-1]
        $analysisProperties = $spec.components.schemas.$analysisSchemaName.properties.PSObject.Properties.Name
        if ($analysisProperties -notcontains 'analysis_data_confirmed') { throw 'OpenAPI AI 分析契约缺少 analysis_data_confirmed' }

        if (-not $spec.components.securitySchemes.BearerAuth) { throw 'OpenAPI 缺少 BearerAuth 安全方案' }
        if (-not $spec.paths.'/api/v1/meetings'.get.security) { throw 'OpenAPI 会议接口未声明访问令牌要求' }
        if ($spec.info.title -ne 'MeetingMind API' -or -not $spec.tags) { throw 'OpenAPI 元数据或分组缺失' }
        Write-Pass '运行中 OpenAPI 文档、访问控制与关键契约'
    } catch {
        Write-Fail "OpenAPI 检查：$($_.Exception.Message)"
    }
} else {
    Write-Warn '已跳过运行中服务与 OpenAPI 检查（-SkipLiveServer）'
}

Invoke-External 'Python 依赖一致性检查' { & $python -m pip check }
Invoke-IsolatedBackendCheck '后端 pytest' { & $python -m pytest -q }
Invoke-IsolatedBackendCheck '受控 Gold Standard 评估' { & $python (Join-Path $root 'evaluation\evaluate.py') --output (Join-Path $env:TEMP 'meetingmind-evaluation.json') --minimum 0.8 }

if (-not $SkipFrontend) {
    $frontend = Join-Path $root 'frontend'
    try { Push-Location $frontend; try { Invoke-NpmAudit } finally { Pop-Location } } catch { Write-Fail "前端生产依赖安全审计：$($_.Exception.Message)" }
    Invoke-External '前端 Vitest' { Push-Location $frontend; try { npm run test } finally { Pop-Location } }
    Invoke-External '前端类型检查与生产构建' { Push-Location $frontend; try { npm run build } finally { Pop-Location } }
} else {
    Write-Warn '已跳过前端测试与构建（-SkipFrontend）'
}

if (Test-Path (Join-Path $root '.git')) {
    try {
        $status = (& git -C $root status --porcelain 2>&1 | Out-String).Trim()
        if ($status) { Write-Warn 'Git 工作区存在未提交修改；发布前应审查并提交或明确排除。' } else { Write-Pass 'Git 工作区干净' }
    } catch { Write-Warn '无法读取 Git 工作区状态' }
} else {
    Write-Warn '项目尚未初始化 Git；无法自动验证待发布文件、提交版本和密钥是否进入版本控制。'
}

Write-Host "`n检查汇总：$($failures.Count) 项失败，$($warnings.Count) 项警告。" -ForegroundColor Cyan
if ($warnings.Count) { $warnings | ForEach-Object { Write-Host "  [WARN] $_" -ForegroundColor Yellow } }
if ($failures.Count) {
    $failures | ForEach-Object { Write-Host "  [FAIL] $_" -ForegroundColor Red }
}

if ($ReportPath) {
    try {
        $report = [pscustomobject]@{
            generated_at = (Get-Date).ToUniversalTime().ToString('o')
            project = 'MeetingMind'
            status = if ($failures.Count) { 'failed' } else { 'passed' }
            failure_count = $failures.Count
            warning_count = $warnings.Count
            failures = @($failures)
            warnings = @($warnings)
            checks = @($checks)
        }
        $reportParent = Split-Path -Parent $ReportPath
        if ($reportParent) { New-Item -ItemType Directory -Force -Path $reportParent | Out-Null }
        $report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding utf8
        Write-Host "检查报告已写入：$ReportPath" -ForegroundColor Cyan
    } catch {
        Write-Host "[WARN] 无法写入检查报告：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

if ($failures.Count) { exit 1 }
Write-Host '发布前自动检查通过；仍须完成 docs/发布前检查清单.md 中的人工发布门槛。' -ForegroundColor Green
