' Launches the Claude Usage Widget with no console window.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python314\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
sh.CurrentDirectory = here
sh.Run """" & pyw & """ """ & here & "\claude_usage_widget.pyw""", 0, False
