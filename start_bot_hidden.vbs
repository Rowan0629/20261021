' Start the bot in the background with no window (put a shortcut to this file in shell:startup).
' ASCII only on purpose: Windows Script Host reads .vbs files in the system ANSI code page,
' so the Chinese-named launcher is found by its "bot.bat" ending instead of by name.
Option Explicit

Dim fso, shell, dir, file
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

For Each file In fso.GetFolder(dir).Files
    If LCase(Right(file.Name, 7)) = "bot.bat" Then
        ' window style 0 = hidden, False = do not wait for it to finish
        shell.Run "cmd /c """ & file.Path & """ hidden", 0, False
        Exit For
    End If
Next
