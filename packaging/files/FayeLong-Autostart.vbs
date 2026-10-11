' ============================================================
'  FayeLong 英语学习网站 —— 开机自启
'
'  本文件由「安装开机自启.bat」复制到 Windows「启动」文件夹，
'  开机登录后在后台拉起服务（不弹窗口、不弹浏览器）。
'  使用：浏览器访问 http://127.0.0.1:8000
'
'  它先从安装记录 %LOCALAPPDATA%\FayeLong\install.txt 读取安装目录，
'  因此本文件放在哪里都能工作；找不到安装目录就安静退出，不打扰开机。
' ============================================================
Option Explicit

Dim fso, sh, root, py, launcher, recFile, f

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

root = ""

' 1) 本脚本所在目录本身就是安装目录？
If fso.FileExists(fso.GetParentFolderName(WScript.ScriptFullName) & "\scripts\launcher.py") Then
    root = fso.GetParentFolderName(WScript.ScriptFullName)
End If

' 2) 否则读安装记录（UTF-16 文本，第 1 行是安装目录）
If root = "" Then
    recFile = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\FayeLong\install.txt"
    If fso.FileExists(recFile) Then
        On Error Resume Next
        Set f = fso.OpenTextFile(recFile, 1, False, -1)
        If Not f Is Nothing Then
            If Not f.AtEndOfStream Then root = Trim(f.ReadLine())
            f.Close
        End If
        On Error GoTo 0
    End If
End If

' 容错：去掉可能存在的尾部反斜杠或引号
Do While Len(root) > 0
    If Right(root, 1) = "\" Or Right(root, 1) = """" Then
        root = Left(root, Len(root) - 1)
    Else
        Exit Do
    End If
Loop

py       = root & "\runtime\python\pythonw.exe"
launcher = root & "\scripts\launcher.py"

' 任何一步找不到就安静退出：开机自启不该弹窗，也不该阻塞登录
If root = "" Then WScript.Quit 0
If Not fso.FileExists(py) Then WScript.Quit 0
If Not fso.FileExists(launcher) Then WScript.Quit 0

sh.CurrentDirectory = root
sh.Run """" & py & """ """ & launcher & """ --silent --no-browser", 0, False
