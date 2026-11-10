' ROZ Bot Control as Administrator, with no console window at all
' (Start-GUI-Admin.cmd does the same but flashes a black window first).
' Needed for auto-login: Windows UIPI blocks SendInput from a normal process
' to the elevated game window.
Option Explicit
Dim fso, here, pyw, script
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = "C:\Users\silap\miniconda3\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
script = here & "\gui\roz_gui.pyw"
CreateObject("Shell.Application").ShellExecute pyw, """" & script & """", here, "runas", 1
