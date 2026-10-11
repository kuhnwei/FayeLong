' ============================================================
'  FayeLong 英语学习网站 —— 静默启动
'
'  双击本文件：在后台启动服务（不会弹出黑色命令窗口），
'             浏览器稍后自动打开，窗口 3 秒后自动消失。
'  停止服务：双击同目录下的「停止 FayeLong.bat」。
'
'  说明：服务用 pythonw.exe 运行，所有输出（含日志）写入
'        data\logs\console.log，遇到问题可查看该文件。
' ============================================================
Option Explicit

Dim fso, sh, root, py, launcher, recDir, ts

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

root     = fso.GetParentFolderName(WScript.ScriptFullName)
py       = root & "\runtime\python\pythonw.exe"
launcher = root & "\scripts\launcher.py"

If Not fso.FileExists(py) Then
    MsgBox "找不到内置的 Python 运行时：" & vbCrLf & vbCrLf & py & vbCrLf & vbCrLf & _
           "请确认压缩包已完整解压（不要只挑几个文件解压），" & vbCrLf & _
           "或改用「启动 FayeLong.bat」查看详细错误。", _
           vbCritical, "FayeLong"
    WScript.Quit 1
End If

If Not fso.FileExists(launcher) Then
    MsgBox "找不到启动脚本：" & vbCrLf & vbCrLf & launcher & vbCrLf & vbCrLf & _
           "请确认压缩包已完整解压，或改用「启动 FayeLong.bat」。", _
           vbCritical, "FayeLong"
    WScript.Quit 1
End If

' 记下安装位置，供「开机自启」与「更新」脚本定位。
' 这里先写占位版本，启动器起来后会补上真实版本与时间。
On Error Resume Next
recDir = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\FayeLong"
If Not fso.FolderExists(recDir) Then fso.CreateFolder(recDir)
If fso.FolderExists(recDir) Then
    Set ts = fso.CreateTextFile(recDir & "\install.txt", True, True)
    ts.WriteLine root
    ts.WriteLine "(启动后自动补全)"
    ts.WriteLine "(启动后自动补全)"
    ts.Close
    Set ts = Nothing
End If
On Error GoTo 0

sh.CurrentDirectory = root
sh.Run """" & py & """ """ & launcher & """ --silent", 0, False

' 3 秒后自动消失的提示（不打断用户）
sh.Popup "FayeLong 正在后台启动..." & vbCrLf & _
         "浏览器稍后会自动打开；停止服务请双击「停止 FayeLong.bat」。", _
         3, "FayeLong", 64
