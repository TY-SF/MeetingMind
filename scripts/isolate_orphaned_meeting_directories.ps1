[CmdletBinding()]
param(
    [string]$DataDir = (Join-Path $PSScriptRoot '..\data'),
    [string]$Container = 'meetingmind-mysql',
    [string]$Database = 'meetingmind',
    [string]$IsolationName = (Get-Date -Format 'yyyyMMdd-HHmmss')
)

$ErrorActionPreference = 'Stop'
if ($Container -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$') { throw 'Docker 容器名称不安全' }
if ($Database -notmatch '^[A-Za-z][A-Za-z0-9_]{0,63}$') { throw '数据库名称不安全' }
if ($IsolationName -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$') { throw '隔离目录名称不安全' }

$dataRoot = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\')
$meetingsRoot = [System.IO.Path]::GetFullPath((Join-Path $dataRoot 'meetings')).TrimEnd('\')
$isolationBase = [System.IO.Path]::GetFullPath((Join-Path $dataRoot 'orphaned-meetings')).TrimEnd('\')
$isolationRoot = [System.IO.Path]::GetFullPath((Join-Path $isolationBase $IsolationName)).TrimEnd('\')
$dataPrefix = $dataRoot + '\'

foreach ($path in @($meetingsRoot, $isolationBase, $isolationRoot)) {
    if (-not $path.StartsWith($dataPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "路径不在数据根目录内：$path"
    }
}
if (-not (Test-Path -LiteralPath $meetingsRoot -PathType Container)) { throw "会议目录不存在：$meetingsRoot" }
if (Test-Path -LiteralPath $isolationRoot) { throw "隔离目标已存在：$isolationRoot" }

$query = 'SELECT id FROM meetings ORDER BY id'
$dbOutput = @(& docker exec -i $Container sh -c 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --batch --skip-column-names -uroot -e "$2" "$1"' meetingmind-isolate $Database $query)
if ($LASTEXITCODE -ne 0) { throw '无法读取 MySQL 会议 ID；未移动任何目录' }
$dbIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($id in $dbOutput) {
    $trimmed = ([string]$id).Trim()
    if ($trimmed) { [void]$dbIds.Add($trimmed) }
}

$directories = @(Get-ChildItem -LiteralPath $meetingsRoot -Directory -Force)
$filesystemIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($directory in $directories) { [void]$filesystemIds.Add($directory.Name) }
$missing = @($dbIds | Where-Object { -not $filesystemIds.Contains($_) })
if ($missing.Count) { throw "数据库存在 $($missing.Count) 个缺失本地目录的会议；未移动任何目录" }
$orphans = @($directories | Where-Object { -not $dbIds.Contains($_.Name) })
if (-not $orphans.Count) {
    Write-Host '未发现孤立会议目录；无需隔离。' -ForegroundColor Green
    exit 0
}

$planned = @()
foreach ($directory in $orphans) {
    if (($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "拒绝移动重解析点目录：$($directory.Name)"
    }
    $source = [System.IO.Path]::GetFullPath($directory.FullName).TrimEnd('\')
    $sourceParent = [System.IO.Path]::GetDirectoryName($source).TrimEnd('\')
    if (-not $sourceParent.Equals($meetingsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "孤立目录不在预期会议根目录内：$($directory.Name)"
    }
    $destination = [System.IO.Path]::GetFullPath((Join-Path $isolationRoot $directory.Name)).TrimEnd('\')
    $isolationPrefix = $isolationRoot + '\'
    if (-not $destination.StartsWith($isolationPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "隔离目标越界：$($directory.Name)"
    }
    if (Test-Path -LiteralPath $destination) { throw "隔离目标冲突：$destination" }
    $planned += [pscustomobject]@{ id = $directory.Name; source = $source; destination = $destination }
}

New-Item -ItemType Directory -Force -Path $isolationRoot | Out-Null
$moved = [System.Collections.Generic.List[object]]::new()
try {
    foreach ($item in $planned) {
        Move-Item -LiteralPath $item.source -Destination $item.destination
        $moved.Add($item)
    }

    $fileRecords = @()
    foreach ($item in $moved) {
        foreach ($file in Get-ChildItem -LiteralPath $item.destination -File -Recurse -Force | Sort-Object FullName) {
            if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "隔离目录包含重解析点文件：$($file.Name)"
            }
            $relative = [System.IO.Path]::GetRelativePath($isolationRoot, $file.FullName).Replace('\', '/')
            $fileRecords += [pscustomobject]@{
                path = $relative
                size = $file.Length
                sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    $manifest = [pscustomobject]@{
        schema_version = 1
        project = 'MeetingMind'
        isolated_at = (Get-Date).ToUniversalTime().ToString('o')
        reason = 'filesystem meeting directory has no corresponding MySQL meetings record'
        source_root = 'data/meetings'
        directory_count = $moved.Count
        directories = @($moved | ForEach-Object { $_.id })
        file_count = $fileRecords.Count
        total_file_bytes = ($fileRecords | Measure-Object -Property size -Sum).Sum
        files = $fileRecords
        deletion_performed = $false
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $isolationRoot 'manifest.json') -Encoding utf8
} catch {
    foreach ($item in @($moved) | Select-Object -Reverse) {
        if ((Test-Path -LiteralPath $item.destination) -and -not (Test-Path -LiteralPath $item.source)) {
            Move-Item -LiteralPath $item.destination -Destination $item.source
        }
    }
    if ((Test-Path -LiteralPath $isolationRoot) -and -not (Get-ChildItem -LiteralPath $isolationRoot -Force)) {
        Remove-Item -LiteralPath $isolationRoot -Force
    }
    throw
}

Write-Host "已隔离 $($moved.Count) 个孤立会议目录；未删除任何数据。" -ForegroundColor Green
Write-Host "隔离位置：$isolationRoot"
Write-Host "清单：$(Join-Path $isolationRoot 'manifest.json')"
