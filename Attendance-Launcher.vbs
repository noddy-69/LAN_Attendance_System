' Launches the Attendance System tray launcher with NO visible console window.
' Double-click this file, or place it in your Startup folder to auto-run at login.
Dim fso, shell, here
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = here
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\Attendance-Launcher.ps1""", 0, False
