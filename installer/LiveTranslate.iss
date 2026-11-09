#ifndef PayloadDir
  #error PayloadDir must point to the prepared application folder
#endif
#ifndef OutputDir
  #error OutputDir must point to the installer output folder
#endif

[Setup]
AppId={{C1AD0775-5F30-4C86-9D6B-708E44F090A2}
AppName=LiveTranslate
AppVersion=1.0.0
AppPublisher=LiveTranslate
DefaultDirName={localappdata}\Programs\LiveTranslate
DefaultGroupName=LiveTranslate
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=LiveTranslate-Setup
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=LiveTranslate.exe
UninstallDisplayIcon={app}\LiveTranslate.exe
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"

[Run]
Filename: "{app}\LiveTranslate.exe"; Description: "Запустить LiveTranslate"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\LiveTranslate\Recordings"
Type: dirifempty; Name: "{localappdata}\LiveTranslate"
