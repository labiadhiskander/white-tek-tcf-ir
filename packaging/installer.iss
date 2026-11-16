; Installateur Windows (Inno Setup 6) – WHITE-TEK TCF IRN B2 MASTER
; Compilation : ISCC.exe /DAppVersion=1.1.0 packaging\installer.iss
; Prérequis : dist\WhiteTekTCF\ produit par PyInstaller (packaging\tcfmaster.spec).

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "WHITE-TEK TCF IRN B2 MASTER"
#define AppExe "WhiteTekTCF.exe"

[Setup]
AppId={{1C03922D-1453-4983-A995-B9F8476827F1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=WHITE-TEK
AppPublisherURL=https://github.com/labiadhiskander/white-tek-tcf-ir
DefaultDirName={autopf}\WhiteTekTCF
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=WhiteTekTCF-Setup-{#AppVersion}
SetupIconFile=..\tcfmaster\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Une mise à jour s'installe par-dessus : l'application doit être fermée.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\dist\WhiteTekTCF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Guide utilisateur"; Filename: "{app}\_internal\tcfmaster\docs\GUIDE_UTILISATEUR.md"
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
french.FinishedLabel=L'installation est terminée. Vos résultats et réglages sont enregistrés dans votre profil Windows (%APPDATA% et %LOCALAPPDATA%) et sont conservés lors des mises à jour et de la désinstallation.
