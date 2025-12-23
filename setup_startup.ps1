$WScriptShell = New-Object -ComObject WScript.Shell
$StartupDir = $WScriptShell.SpecialFolders.Item("Startup")
$ShortcutPath = Join-Path -Path $StartupDir -ChildPath "VoiceCloneApp.lnk"
$TargetPath = "d:\project\voice\run.bat"
$IconPath = "d:\project\voice\static\favicon.ico" # Optional, if exists

$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = "d:\project\voice"
$Shortcut.Description = "Start Voice Clone App"
# $Shortcut.IconLocation = $IconPath # Uncomment if icon exists
$Shortcut.Save()

Write-Host "Shortcut created at: $ShortcutPath"
Write-Host "The app will now start automatically when you log in."
