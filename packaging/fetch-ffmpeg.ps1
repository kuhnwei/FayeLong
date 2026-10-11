# 下载便携版 ffmpeg / ffprobe 到 tools/ffmpeg（源：npmmirror，国内速度快）
# 已存在则跳过；下载的是免解压的独立可执行文件。
# 用法： powershell -ExecutionPolicy Bypass -File packaging\fetch-ffmpeg.ps1
$ErrorActionPreference = 'Stop'

$ver  = 'b6.1.1'
$base = "https://registry.npmmirror.com/-/binary/ffmpeg-static/$ver"
$root = Split-Path -Parent $PSScriptRoot
$dir  = Join-Path $root 'tools\ffmpeg'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$failed = $false
foreach ($name in @('ffmpeg', 'ffprobe')) {
    $exe = Join-Path $dir "$name.exe"
    if (Test-Path $exe) {
        Write-Host "[skip] $name.exe already exists"
        continue
    }
    Write-Host "[get ] $name.exe ..."
    & curl.exe -L --retry 3 -s "$base/$name-win32-x64" -o $exe
    if ((Test-Path $exe) -and ((Get-Item $exe).Length -gt 10MB)) {
        Write-Host "[ok  ] $exe"
    } else {
        Write-Host "[FAIL] $name.exe"
        $failed = $true
    }
}

if ($failed) { exit 1 }
Write-Host "done."
