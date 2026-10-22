#Requires -Version 5.1
<#
.SYNOPSIS
    产出 FayeLong「就地更新包」—— 只含程序文件，不含运行时 / 模型 / 词典。

.DESCRIPTION
    完整交付包约 816MB（zip），其中绝大部分是 Python 运行时、whisper 模型与
    ECDICT 词典 —— 版本更新时这些通常**完全不变**。
    本脚本只打包会变的程序文件（app / static / scripts / 顶层脚本），
    体积通常只有几 MB ~ 几十 MB，配合「更新 FayeLong.bat」就能把旧安装目录
    升级到新版，而且**绝不改动 data/ 里的学习数据**。

    用法：把 zip 解压到**新目录**，双击其中的「更新 FayeLong.bat」，
    指向旧安装目录（或把旧目录拖到该文件上）。

.PARAMETER NoZip
    只产出 dist\FayeLong-update 目录，不压缩成 zip。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build-update.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build-update.ps1 -NoZip
#>
[CmdletBinding()]
param(
    [switch]$NoZip,
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# 解压后的目录名刻意与完整包不同（FayeLong / FayeLong-update），避免用户误覆盖
$Name  = 'FayeLong-update'
$Pack  = $PSScriptRoot
$Root  = Split-Path -Parent $Pack
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $Root 'dist' }
$Stage = Join-Path $OutDir $Name
$Tmp   = Join-Path $Pack 'tmp'

$ScriptsIn = Join-Path $Stage 'scripts'

# 前端构建产物来源（P5 起为 Vue 版：frontend-vue\dist，拷进包里成为 static\）。
# ⚠️ 与 build.ps1 保持同一口径的**单一变量**：预检 / 错误提示 / Copy-Tree 全用它。
$FrontendDist = Join-Path $Root 'frontend-vue\dist'

$Utf8NoBom  = New-Object System.Text.UTF8Encoding($false)
$Utf16LeBom = New-Object System.Text.UnicodeEncoding($false, $true)

# ---------------------------------------------------------------- 输出

function Step([string]$text) {
    Write-Host ''
    Write-Host ('=' * 68) -ForegroundColor DarkGray
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor DarkGray
}
function Info([string]$text) { Write-Host "  · $text" }
function Good([string]$text) { Write-Host "  [OK] $text" -ForegroundColor Green }
function Note([string]$text) { Write-Host "  [!!] $text" -ForegroundColor Yellow }
function Fail([string]$text) { Write-Host "  [XX] $text" -ForegroundColor Red }

function Format-Size([long]$bytes) {
    if ($bytes -ge 1GB) { return ('{0:N2} GB' -f ($bytes / 1GB)) }
    if ($bytes -ge 1MB) { return ('{0:N1} MB' -f ($bytes / 1MB)) }
    if ($bytes -ge 1KB) { return ('{0:N1} KB' -f ($bytes / 1KB)) }
    return "$bytes B"
}

function Get-TreeSize([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { return 0 }
    return [long]$sum
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target,
        [string[]]$ExcludeDir = @(),
        [string[]]$ExcludeFile = @()
    )
    if (-not (Test-Path -LiteralPath $Source)) { throw "源目录不存在：$Source" }
    $null = New-Item -ItemType Directory -Force -Path $Target
    $argv = @($Source, $Target, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    if ($ExcludeDir.Count -gt 0) { $argv += '/XD'; $argv += $ExcludeDir }
    if ($ExcludeFile.Count -gt 0) { $argv += '/XF'; $argv += $ExcludeFile }
    & robocopy @argv | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败（$LASTEXITCODE）：$Source -> $Target" }
}

function Copy-FileSafe([string]$Source, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Source)) { throw "源文件不存在：$Source" }
    $dir = Split-Path -Parent $Target
    $null = New-Item -ItemType Directory -Force -Path $dir
    Copy-Item -LiteralPath $Source -Destination $Target -Force
}

function Write-TextFile([string]$Path, [string]$Text, [switch]$Crlf) {
    if ($Crlf) { $Text = ($Text -replace "`r`n", "`n") -replace "`n", "`r`n" }
    $dir = Split-Path -Parent $Path
    $null = New-Item -ItemType Directory -Force -Path $dir
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Write-TextFileUtf16([string]$Path, [string]$Text) {
    $Text = ($Text -replace "`r`n", "`n") -replace "`n", "`r`n"
    $dir = Split-Path -Parent $Path
    $null = New-Item -ItemType Directory -Force -Path $dir
    [System.IO.File]::WriteAllText($Path, $Text, $Utf16LeBom)
}

# ================================================================ 开始

$startedAt = Get-Date
Step 'FayeLong 就地更新包构建（只含程序文件）'

$version = '0.0.0'
$initPy = Join-Path $Root 'backend\app\__init__.py'
if (Test-Path -LiteralPath $initPy) {
    $m = Select-String -LiteralPath $initPy -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($m) { $version = $m.Matches[0].Groups[1].Value }
}
$buildDate = (Get-Date).ToString('yyyy-MM-dd HH:mm')
Info "版本 $version     构建于 $buildDate"
Info "输出目录 $OutDir"

# ---------------------------------------------------------------- 0 前置检查

Step '0/5  前置检查'
if (-not (Test-Path -LiteralPath (Join-Path $Root 'backend\app\main.py'))) {
    Fail "找不到后端代码：$Root\backend\app"
    exit 1
}
Good '后端代码就绪'

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist 'index.html'))) {
    Fail "前端尚未构建：缺少 $(Join-Path $FrontendDist 'index.html')"
    Fail '请先在 frontend-vue 目录执行： npm install --ignore-scripts ; npx vite build'
    exit 1
}
Good '前端构建产物就绪'

$devPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $devPy)) {
    $devPy = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $devPy) {
    Fail '找不到可用的 Python（既没有 backend\.venv，也没有 PATH 里的 python）'
    exit 1
}
Info "构建用 Python：$devPy"

# ---------------------------------------------------------------- 1 目录

Step '1/5  准备输出目录'
if (Test-Path -LiteralPath $Stage) {
    try {
        Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction Stop
        Good '已清理旧的输出目录'
    } catch {
        $keep = "$Stage.old-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Note "旧目录删不掉（可能被占用），改名为：$(Split-Path -Leaf $keep)"
        Rename-Item -LiteralPath $Stage -NewName (Split-Path -Leaf $keep)
    }
}
$null = New-Item -ItemType Directory -Force -Path $Stage
Good "输出目录：$Stage"

# ---------------------------------------------------------------- 2 程序代码

Step '2/5  复制程序文件（app / static / scripts）'
Copy-Tree -Source (Join-Path $Root 'backend\app') -Target (Join-Path $Stage 'app') `
    -ExcludeDir @('__pycache__') -ExcludeFile @('*.pyc')
Good "后端代码 -> app\（$(Format-Size (Get-TreeSize (Join-Path $Stage 'app')))）"

Copy-Tree -Source $FrontendDist -Target (Join-Path $Stage 'static')
Good "前端产物 -> static\（$(Format-Size (Get-TreeSize (Join-Path $Stage 'static')))）"

$null = New-Item -ItemType Directory -Force -Path $ScriptsIn
Copy-FileSafe -Source (Join-Path $Pack 'launcher.py')  -Target (Join-Path $ScriptsIn 'launcher.py')
# worker 启动垫片（embeddable Python 忽略 PYTHONPATH，必须随包更新，否则就地更新
# 到 P3-6 之后的版本时 worker 会起不来 —— 详见 packaging/worker_entry.py）。
Copy-FileSafe -Source (Join-Path $Pack 'worker_entry.py') -Target (Join-Path $ScriptsIn 'worker_entry.py')
Copy-FileSafe -Source (Join-Path $Pack 'bootstrap.py') -Target (Join-Path $ScriptsIn 'bootstrap.py')
Copy-FileSafe -Source (Join-Path $Pack 'update.py')    -Target (Join-Path $ScriptsIn 'update.py')
Copy-FileSafe -Source (Join-Path $Root 'backend\scripts\selftest.py')   -Target (Join-Path $ScriptsIn 'selftest.py')
Copy-FileSafe -Source (Join-Path $Root 'backend\scripts\fetch_dict.py') -Target (Join-Path $ScriptsIn 'fetch_dict.py')
Good '启动器 / worker 垫片 / 资源下载 / 就地更新脚本 -> scripts\'

# ---------------------------------------------------------------- 3 用户文件

Step '3/5  生成用户文件'
$batFiles = @(
    '启动 FayeLong.bat',
    '停止 FayeLong.bat',
    '更新 FayeLong.bat',
    '安装开机自启.bat',
    '取消开机自启.bat'
)
foreach ($bat in $batFiles) {
    $src = Join-Path $Pack "files\$bat"
    if (-not (Test-Path -LiteralPath $src)) { Fail "缺少用户脚本：$src"; exit 1 }
    $text = [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8)
    Write-TextFile -Path (Join-Path $Stage $bat) -Text $text -Crlf
    Good $bat
}
foreach ($vbs in @('静默启动 FayeLong.vbs', 'FayeLong-Autostart.vbs')) {
    $src = Join-Path $Pack "files\$vbs"
    if (-not (Test-Path -LiteralPath $src)) { Fail "缺少用户脚本：$src"; exit 1 }
    $text = [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8)
    Write-TextFileUtf16 -Path (Join-Path $Stage $vbs) -Text $text
    Good "$vbs（UTF-16 编码）"
}

$readmeSrc = Join-Path $Pack 'files\使用说明.txt'
$readme = [System.IO.File]::ReadAllText($readmeSrc, [System.Text.Encoding]::UTF8)
$modeText = '就地更新包（只含程序文件，需在旧安装目录上执行更新）'
$readme = $readme.Replace('{{VERSION}}', $version).Replace('{{BUILD_DATE}}', $buildDate).Replace('{{MODE}}', $modeText)
Write-TextFile -Path (Join-Path $Stage '使用说明.txt') -Text $readme -Crlf
Good '使用说明.txt'

# ---------------------------------------------------------------- 4 自检

Step '4/5  自检（语法 + 编码）'
# 子进程（Python）在被重定向时按 UTF-8 输出，这里同步解码方式，避免中文乱码
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    Note '无法将控制台输出编码设为 UTF-8，自检输出中文可能显示为乱码（不影响结果）'
}
# 更新包不带运行时，无法跑 launcher --check；改为对全部 .py 做语法检查
& $devPy (Join-Path $Pack 'check_syntax.py') $Stage
if ($LASTEXITCODE -ne 0) {
    Fail '语法检查未通过，更新包不可用'
    exit 1
}

# .vbs 必须是 UTF-16LE 且带 BOM，否则 WSH 会乱码 / 报错
foreach ($vbs in @('静默启动 FayeLong.vbs', 'FayeLong-Autostart.vbs')) {
    $path = Join-Path $Stage $vbs
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 2 -or $bytes[0] -ne 0xFF -or $bytes[1] -ne 0xFE) {
        Fail "$vbs 不是 UTF-16LE(BOM) 编码，Windows Script Host 可能无法正确读取"
        exit 1
    }
}
Good '.vbs 编码正确（UTF-16LE + BOM）'

# 更新包绝不能带 data/（避免任何覆盖用户数据的可能）
if (Test-Path -LiteralPath (Join-Path $Stage 'data')) {
    Fail '更新包里不允许出现 data\ 目录 —— 它只应包含程序文件'
    exit 1
}
Good '不含 data\ 目录（从设计上杜绝覆盖用户数据）'

# ---------------------------------------------------------------- 5 压缩

$total = Get-TreeSize $Stage
Step '5/5  汇总'

if (-not $NoZip) {
    $zipPath = Join-Path $OutDir "FayeLong-update-v$version-win64.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Info "打包 $zipPath"
    $zipper = Join-Path $Pack 'zipdir.py'
    & $devPy $zipper $Stage $zipPath --root $Name
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $zipPath)) {
        Fail '压缩失败'
        exit 1
    }
    $zipItem = Get-Item -LiteralPath $zipPath
    Good ("压缩完成：{0}（{1}）" -f $zipItem.Name, (Format-Size $zipItem.Length))
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    $hashFile = "$zipPath.sha256.txt"
    Write-TextFile -Path $hashFile -Text ("{0}  {1}`n" -f $hash, $zipItem.Name)
    Good "SHA256：$hash"
} else {
    Info '（-NoZip：未压缩）'
}

Step '全部完成'
Info "更新包目录：$Stage"
Info "目录体积：$(Format-Size $total)"
Info ('总耗时 {0:N1} 分钟' -f ((Get-Date) - $startedAt).TotalMinutes)
Info ''
Info '目标机用法：解压到新目录 → 双击「更新 FayeLong.bat」→ 指定旧安装目录。'
Info '更新只替换程序文件，data\ 里的学习数据不会被改动。'
