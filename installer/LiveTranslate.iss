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
ArchiveExtraction=full
CloseApplications=yes
CloseApplicationsFilter=LiveTranslate.exe
UninstallDisplayIcon={app}\LiveTranslate.exe
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "nvidia"; Description: "Ускорение NVIDIA (загрузка около 1,3 ГБ; нужен интернет)"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "\_internal\nvidia\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "cublas.zip"; ExternalSize: 1200000000; Hash: "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/c7/bd/1d6709d2223e99f04079f16005f8ae6e11a14ee16b5eab6833686cf72fe1/nvidia_cudnn_cu12-9.28.1.4-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "cudnn.zip"; ExternalSize: 1500000000; Hash: "3467aafa9b260e6adf5fbbfc0e21d180133305b42032aa1160be2d3142bb8b09"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/52/de/823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "nvrtc.zip"; ExternalSize: 160000000; Hash: "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"

[Run]
Filename: "{app}\LiveTranslate.exe"; Description: "Запустить LiveTranslate"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\LiveTranslate\Recordings"
Type: dirifempty; Name: "{localappdata}\LiveTranslate"
