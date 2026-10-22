#Requires -Version 5.1
<#
.SYNOPSIS
    FayeLong 交付包构建脚本（M6 打包与交付）。

.DESCRIPTION
    在开发机上一条命令产出「可在没有开发环境的 Windows 笔记本上一键运行」的交付包：

        runtime\python        内置 Python 3.13 嵌入版运行时
        runtime\python\Lib\site-packages   全部第三方依赖（faster-whisper 等）
        runtime\ffmpeg        便携版 ffmpeg / ffprobe
        app\                  后端代码
        static\               前端构建产物
        scripts\              启动器 / 自检 / 资源下载 / 就地更新
        data\                 运行时数据（模型、词典、学习数据）
        启动 FayeLong.bat     双击启动（带控制台窗口，便于排错）
        静默启动 FayeLong.vbs 后台启动（无窗口，浏览器自动打开）
        安装开机自启.bat      让它在每次开机后自动在后台运行
        更新 FayeLong.bat     把新版程序更新到旧安装目录，**不动学习数据**
        停止 FayeLong.bat     停止服务
        使用说明.txt

    只要程序文件（不含运行时的「更新包」）请用 packaging\build-update.ps1。

.PARAMETER Light
    轻量模式：不内置语音识别模型（约 460MB）与离线词典（约 810MB），
    改为首次启动时按需下载。交付包体积从约 1.3GB 降到约 0.5GB。

.PARAMETER FromPip
    用 pip 重新下载安装依赖（默认直接复用 backend\.venv 里已验证的依赖，更快）。

.PARAMETER NoZip
    只产出 dist\FayeLong 目录，不压缩成 zip。

.PARAMETER Force
    即使内置运行时已存在也重新下载。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Light
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -NoZip -OutDir D:\out
#>
[CmdletBinding()]
param(
    [switch]$Light,
    [switch]$FromPip,
    [switch]$NoZip,
    [switch]$Force,
    [string]$PythonVersion = '3.13.14',
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # Invoke-WebRequest 提速

$Name  = 'FayeLong'
$Pack  = $PSScriptRoot
$Root  = Split-Path -Parent $Pack
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $Root 'dist' }
$Stage = Join-Path $OutDir $Name
$Tmp   = Join-Path $Pack 'tmp'

$PyDir     = Join-Path $Stage 'runtime\python'
$SiteDir   = Join-Path $PyDir 'Lib\site-packages'
$ScriptsIn = Join-Path $Stage 'scripts'
$DataDir   = Join-Path $Stage 'data'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
# .vbs 必须存成 UTF-16LE + BOM：Windows Script Host 不认 UTF-8，含中文会乱码甚至报语法错误
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

# ---------------------------------------------------------------- 工具

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
    if ($Crlf) {
        $Text = ($Text -replace "`r`n", "`n") -replace "`n", "`r`n"
    }
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

function Download-First([string[]]$Urls, [string]$Target) {
    $dir = Split-Path -Parent $Target
    $null = New-Item -ItemType Directory -Force -Path $dir
    foreach ($url in $Urls) {
        Info "下载 $url"
        try {
            Invoke-WebRequest -Uri $url -OutFile $Target -UseBasicParsing -TimeoutSec 600
            if ((Test-Path -LiteralPath $Target) -and (Get-Item -LiteralPath $Target).Length -gt 1MB) {
                Good ("完成：{0}（{1}）" -f (Split-Path -Leaf $Target), (Format-Size (Get-Item -LiteralPath $Target).Length))
                return $true
            }
            Note "文件过小，换下一个镜像"
        } catch {
            Note ("失败：{0}" -f $_.Exception.Message)
        }
    }
    return $false
}

# ================================================================ 开始

$startedAt = Get-Date
Step "FayeLong 交付包构建（$(if ($Light) { '轻量模式' } else { '全量模式' })）"

$version = '0.0.0'
$initPy = Join-Path $Root 'backend\app\__init__.py'
if (Test-Path -LiteralPath $initPy) {
    $m = Select-String -LiteralPath $initPy -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($m) { $version = $m.Matches[0].Groups[1].Value }
}
$buildDate = (Get-Date).ToString('yyyy-MM-dd HH:mm')
$modeText = if ($Light) { '轻量包（首次运行自动下载模型与词典）' } else { '全量包（内置模型与词典）' }
Info "版本 $version     构建于 $buildDate"
Info "输出目录 $OutDir"

# ---------------------------------------------------------------- 0 前置检查

Step '0/9  前置检查'

if (-not (Test-Path -LiteralPath (Join-Path $Root 'backend\app\main.py'))) {
    Fail "找不到后端代码：$Root\backend\app"
    exit 1
}
Good '后端代码就绪'

$distIndex = Join-Path $Root 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $distIndex)) {
    Fail '前端尚未构建：缺少 frontend\dist\index.html'
    Fail '请先在 frontend 目录执行： npm install --ignore-scripts ; npx vite build'
    exit 1
}
Good '前端构建产物就绪'

$ffSrc = Join-Path $Root 'tools\ffmpeg'
if (-not (Test-Path -LiteralPath (Join-Path $ffSrc 'ffmpeg.exe'))) {
    Note '未找到便携版 ffmpeg，尝试自动下载 …'
    & (Join-Path $Pack 'fetch-ffmpeg.ps1')
    if (-not (Test-Path -LiteralPath (Join-Path $ffSrc 'ffmpeg.exe'))) {
        Fail 'ffmpeg 下载失败，请手动执行 packaging\fetch-ffmpeg.ps1 后重试'
        exit 1
    }
}
Good '便携版 ffmpeg / ffprobe 就绪'

$venvSite = Join-Path $Root 'backend\.venv\Lib\site-packages'
$devPy = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $devPy)) {
    $devPy = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $devPy) {
    Fail '找不到可用的 Python（既没有 backend\.venv，也没有 PATH 里的 python）'
    Fail '请先按 README 建立后端虚拟环境： python -m venv backend\.venv'
    exit 1
}
Info "构建用 Python：$devPy"

if (-not $FromPip -and -not (Test-Path -LiteralPath $venvSite)) {
    Note "未找到 $venvSite，将改用 pip 下载依赖"
    $FromPip = $true
}
if ($FromPip) { Info '依赖来源：pip 在线安装' } else { Info '依赖来源：复用 backend\.venv（已验证可用）' }

$modelSrc = Join-Path $Root 'data\models\faster-whisper-small'
$dictSrc  = Join-Path $Root 'data\dict\ecdict.db'
if (-not $Light) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelSrc 'model.bin'))) {
        Fail "缺少语音识别模型：$modelSrc\model.bin"
        Fail '请先运行 backend\.venv\Scripts\python.exe backend\scripts\selftest.py --asr 触发下载，或改用 -Light'
        exit 1
    }
    if (-not (Test-Path -LiteralPath $dictSrc)) {
        Fail "缺少离线词典：$dictSrc"
        Fail '请先运行 backend\.venv\Scripts\python.exe backend\scripts\fetch_dict.py，或改用 -Light'
        exit 1
    }
    Good '模型与词典就绪（全量模式）'
} else {
    Info '轻量模式：模型与词典不随包，首次启动下载'
}

# ---------------------------------------------------------------- 1 目录

Step '1/9  准备输出目录'
if (Test-Path -LiteralPath $Stage) {
    # 优先直接清空；若目录里有进程占用（例如上次的服务还在跑）或受策略拦截，
    # 则改名保留（同盘改名是瞬时的），保证构建不中断。
    try {
        Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction Stop
        Good "已清空旧的 $Stage"
    } catch {
        $backup = Join-Path $OutDir ("$Name.old-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Note "无法删除旧的 $Stage（$($_.Exception.Message)）"
        Note "已改名为 $backup，确认无用后可手动删除（同盘改名不占额外空间）"
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
        Move-Item -LiteralPath $Stage -Destination $backup
    }
}
$null = New-Item -ItemType Directory -Force -Path $Stage
$null = New-Item -ItemType Directory -Force -Path $Tmp
Good "输出目录就绪：$Stage"

# ---------------------------------------------------------------- 2 Python

Step "2/9  装配内置 Python $PythonVersion（嵌入版）"
$pyExe = Join-Path $PyDir 'python.exe'
if ((Test-Path -LiteralPath $pyExe) -and -not $Force) {
    Good '内置运行时已存在，跳过下载（-Force 可强制重下）'
} else {
    $base = "python-$PythonVersion-embed-amd64.zip"
    $urls = @(
        "https://registry.npmmirror.com/-/binary/python/$PythonVersion/$base",
        "https://mirrors.huaweicloud.com/python/$PythonVersion/$base",
        "https://www.python.org/ftp/python/$PythonVersion/$base"
    )
    $zip = Join-Path $Tmp $base
    if ((Test-Path -LiteralPath $zip) -and (Get-Item -LiteralPath $zip).Length -gt 5MB) {
        Good ("复用已下载的压缩包（{0}）" -f (Format-Size (Get-Item -LiteralPath $zip).Length))
    } elseif (-not (Download-First -Urls $urls -Target $zip)) {
        Fail 'Python 嵌入版下载失败，请检查网络后重试'
        exit 1
    }
    $null = New-Item -ItemType Directory -Force -Path $PyDir
    Expand-Archive -LiteralPath $zip -DestinationPath $PyDir -Force
    Good "已解压到 $PyDir"
}

# ---------------------------------------------------------------- 3 _pth

$pthFile = Get-ChildItem -LiteralPath $PyDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) {
    Fail "内置运行时里找不到 python*._pth：$PyDir"
    exit 1
}
Write-TextFile -Path $pthFile.FullName -Text "python313.zip`n.`nLib\site-packages`nimport site`n" -Crlf
Good "已写入 $($pthFile.Name)（启用 Lib\site-packages）"

# ---------------------------------------------------------------- 4 依赖

Step '4/9  装配第三方依赖'
if ($FromPip) {
    if (Test-Path -LiteralPath $SiteDir) { Remove-Item -LiteralPath $SiteDir -Recurse -Force }
    $null = New-Item -ItemType Directory -Force -Path $SiteDir
    $reqs = @(
        (Join-Path $Root 'backend\requirements.txt'),
        (Join-Path $Root 'backend\requirements-ml.txt')
    )
    foreach ($req in $reqs) {
        Info "pip install -r $(Split-Path -Leaf $req)"
        & $devPy -m pip install --quiet --upgrade --target $SiteDir `
            --only-binary=:all: --python-version 3.13 --platform win_amd64 `
            --index-url https://pypi.tuna.tsinghua.edu.cn/simple `
            -r $req
        if ($LASTEXITCODE -ne 0) { Fail "pip 安装失败：$req"; exit 1 }
    }
    Good "依赖已安装：$(Format-Size (Get-TreeSize $SiteDir))"
} else {
    Info '复制 backend\.venv\Lib\site-packages（保留 __pycache__ 以加快首次启动）'
    Copy-Tree -Source $venvSite -Target $SiteDir
    Good "依赖已复制：$(Format-Size (Get-TreeSize $SiteDir))"
}

# ---------------------------------------------------------------- 5 VC++ 运行库

Step '5/9  补齐 VC++ 运行库（目标机可能没装 VC++ Redist）'
$needDlls = @('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll', 'concrt140.dll')
$copied = 0
foreach ($dll in $needDlls) {
    $target = Join-Path $PyDir $dll
    if (Test-Path -LiteralPath $target) { continue }
    $src = Join-Path $env:SystemRoot "System32\$dll"
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination $target -Force
        $copied++
    } else {
        Note "本机也找不到 $dll（可忽略，目标机通常自带）"
    }
}
if ($copied -gt 0) { Good "已随包附带 $copied 个 VC++ 运行库 DLL" } else { Good 'VC++ 运行库无需补齐' }

# ---------------------------------------------------------------- 6 代码 / 前端 / 脚本

Step '6/9  复制应用代码、前端产物与脚本'
Copy-Tree -Source (Join-Path $Root 'backend\app') -Target (Join-Path $Stage 'app') `
    -ExcludeDir @('__pycache__') -ExcludeFile @('*.pyc')
Good "后端代码 -> app\（$(Format-Size (Get-TreeSize (Join-Path $Stage 'app')))）"

Copy-Tree -Source (Join-Path $Root 'tools\ffmpeg') -Target (Join-Path $Stage 'runtime\ffmpeg') `
    -ExcludeFile @('.gitkeep')
Good "ffmpeg -> runtime\ffmpeg\（$(Format-Size (Get-TreeSize (Join-Path $Stage 'runtime\ffmpeg')))）"

Copy-Tree -Source (Join-Path $Root 'frontend\dist') -Target (Join-Path $Stage 'static')
Good "前端产物 -> static\（$(Format-Size (Get-TreeSize (Join-Path $Stage 'static')))）"

$null = New-Item -ItemType Directory -Force -Path $ScriptsIn
Copy-FileSafe -Source (Join-Path $Pack 'launcher.py')  -Target (Join-Path $ScriptsIn 'launcher.py')
# worker 启动垫片：embeddable Python 忽略 PYTHONPATH，`python -m app.worker` 在
# 交付包形态下必然 No module named 'app'（详见 packaging/worker_entry.py）。
Copy-FileSafe -Source (Join-Path $Pack 'worker_entry.py') -Target (Join-Path $ScriptsIn 'worker_entry.py')
Copy-FileSafe -Source (Join-Path $Pack 'bootstrap.py') -Target (Join-Path $ScriptsIn 'bootstrap.py')
Copy-FileSafe -Source (Join-Path $Pack 'update.py')    -Target (Join-Path $ScriptsIn 'update.py')
Copy-FileSafe -Source (Join-Path $Root 'backend\scripts\selftest.py')   -Target (Join-Path $ScriptsIn 'selftest.py')
Copy-FileSafe -Source (Join-Path $Root 'backend\scripts\fetch_dict.py') -Target (Join-Path $ScriptsIn 'fetch_dict.py')
Good '启动器 / worker 垫片 / 自检 / 资源下载 / 就地更新脚本 -> scripts\'

# ---------------------------------------------------------------- 7 数据

Step '7/9  准备 data 目录'
foreach ($d in @('media\audio', 'media\library', 'logs')) {
    $null = New-Item -ItemType Directory -Force -Path (Join-Path $DataDir $d)
}
Write-TextFile -Path (Join-Path $DataDir 'media\audio\把音频文件放这里.txt') -Text @"
把要学习的音频 / 视频文件直接放进这个文件夹，
然后在网站首页点「从收件箱导入」即可。

支持格式：
  音频  mp3 / wav / m4a / flac / aac / ogg / opus / wma
  视频  mp4 / mkv / mov / webm / avi / flv / m4v / ts
"@ -Crlf

if (-not $Light) {
    Copy-Tree -Source $modelSrc -Target (Join-Path $DataDir 'models\faster-whisper-small')
    Good "语音识别模型 -> data\models\（$(Format-Size (Get-TreeSize (Join-Path $DataDir 'models')))）"

    $null = New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'dict')
    Copy-FileSafe -Source $dictSrc -Target (Join-Path $DataDir 'dict\ecdict.db')
    $metaSrc = Join-Path $Root 'data\dict\ecdict.meta.json'
    if (Test-Path -LiteralPath $metaSrc) {
        Copy-FileSafe -Source $metaSrc -Target (Join-Path $DataDir 'dict\ecdict.meta.json')
    }
    Good "离线词典 -> data\dict\（$(Format-Size (Get-TreeSize (Join-Path $DataDir 'dict')))）"
} else {
    Info '轻量模式：跳过模型与词典'
}

# ---------------------------------------------------------------- 8 用户文件

Step '8/9  生成用户文件（启动 / 停止 / 静默启动 / 开机自启 / 更新 / 说明）'
# .bat：UTF-8（无 BOM）+ CRLF —— 配合脚本里的 chcp 65001，中文提示正常
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
# .vbs：必须 UTF-16LE + BOM，Windows Script Host 不认 UTF-8（中文会乱码 / 报语法错误）
foreach ($vbs in @('静默启动 FayeLong.vbs', 'FayeLong-Autostart.vbs')) {
    $src = Join-Path $Pack "files\$vbs"
    if (-not (Test-Path -LiteralPath $src)) { Fail "缺少用户脚本：$src"; exit 1 }
    $text = [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8)
    Write-TextFileUtf16 -Path (Join-Path $Stage $vbs) -Text $text
    Good "$vbs（UTF-16 编码）"
}
$readmeSrc = Join-Path $Pack 'files\使用说明.txt'
$readme = [System.IO.File]::ReadAllText($readmeSrc, [System.Text.Encoding]::UTF8)
$readme = $readme.Replace('{{VERSION}}', $version).Replace('{{BUILD_DATE}}', $buildDate).Replace('{{MODE}}', $modeText)
Write-TextFile -Path (Join-Path $Stage '使用说明.txt') -Text $readme -Crlf
Good '使用说明.txt'

# ---------------------------------------------------------------- 9 自检

Step '9/9  用打包运行时自检（模拟目标机）'
# 子进程（Python）在被重定向时按 UTF-8 输出，这里同步解码方式，避免中文乱码
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    Note '无法将控制台输出编码设为 UTF-8，自检输出中文可能显示为乱码（不影响结果）'
}
$launcher = Join-Path $ScriptsIn 'launcher.py'
Push-Location $Stage
try {
    & $pyExe $launcher --check
    $checkCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($checkCode -ne 0) {
    Fail '打包自检未通过，交付包不可用（详见上方输出）'
    exit 1
}
Good '自检通过'

# ---------------------------------------------------------------- 汇总

$total = Get-TreeSize $Stage
Step '构建完成'
Info "交付目录：$Stage"
Info "目录体积：$(Format-Size $total)"
Info "版本：$version    模式：$modeText"

if (-not $NoZip) {
    Step '压缩为 zip'
    $zipPath = Join-Path $OutDir "$Name-v$version-win64.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Info "打包 $zipPath（内置模型与词典时约需几分钟，请耐心等待）"
    # 必须用 Python 的 zipfile 而非 tar.exe：Windows 自带 bsdtar 会把中文名按
    # GBK 写入且不置 UTF-8 标志，7-Zip / macOS / 非中文 Windows 解压会乱码。
    $zipper = Join-Path $Pack 'zipdir.py'
    $zipOk = $false
    if ((Test-Path -LiteralPath $zipper) -and $devPy) {
        & $devPy $zipper $Stage $zipPath --root $Name
        $zipOk = ($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $zipPath)
    }
    if (-not $zipOk) {
        Note 'Python 打包失败，回退到 tar（中文文件名可能在部分解压工具下乱码）'
        $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (Test-Path -LiteralPath $tar) {
            & $tar -a -c -f $zipPath -C $OutDir $Name
        } else {
            Compress-Archive -Path $Stage -DestinationPath $zipPath -Force
        }
    }
    $zipItem = Get-Item -LiteralPath $zipPath
    Good ("压缩完成：{0}（{1}）" -f $zipItem.Name, (Format-Size $zipItem.Length))
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    $hashFile = "$zipPath.sha256.txt"
    Write-TextFile -Path $hashFile -Text ("{0}  {1}`n" -f $hash, $zipItem.Name)
    Good "SHA256：$hash"
    Info "校验值已写入：$hashFile"
}

Step '全部完成'
$elapsed = (Get-Date) - $startedAt
Info ("总耗时 {0:N1} 分钟" -f $elapsed.TotalMinutes)
Info '把 dist\FayeLong 整个文件夹拷到目标笔记本，双击「启动 FayeLong.bat」即可。'
