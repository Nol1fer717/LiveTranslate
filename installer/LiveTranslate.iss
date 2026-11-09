#ifndef PayloadDir
  #error PayloadDir must point to the prepared application folder
#endif
#ifndef OutputDir
  #error OutputDir must point to the installer output folder
#endif

[Setup]
AppId={{C1AD0775-5F30-4C86-9D6B-708E44F090A2}
AppName=LiveTranslate
AppVersion=1.2.0
AppPublisher=LiveTranslate
DefaultDirName={autopf}\LiveTranslate
DefaultGroupName=LiveTranslate
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=LiveTranslate-Setup
Compression=lzma2/max
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
Name: "german"; Description: "Немецкий язык: перевод на русский (загрузка около 300 МБ)"; Flags: unchecked
Name: "speakers"; Description: "Различать голоса собеседников (загрузка около 14 МБ)"; Flags: unchecked
Name: "nvidia"; Description: "Ускорение NVIDIA (загрузка около 1,3 ГБ; нужен интернет)"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "\_internal\nvidia\*,\data\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/model.bin"; DestDir: "{app}\data\whisper-small"; DestName: "model.bin"; ExternalSize: 486197344; Hash: "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"; Flags: external download ignoreversion
Source: "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/config.json"; DestDir: "{app}\data\whisper-small"; DestName: "config.json"; ExternalSize: 2200; Hash: "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"; Flags: external download ignoreversion
Source: "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/tokenizer.json"; DestDir: "{app}\data\whisper-small"; DestName: "tokenizer.json"; ExternalSize: 2200000; Hash: "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"; Flags: external download ignoreversion
Source: "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/vocabulary.txt"; DestDir: "{app}\data\whisper-small"; DestName: "vocabulary.txt"; ExternalSize: 500000; Hash: "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"; Flags: external download ignoreversion
Source: "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel"; DestDir: "{app}\data"; DestName: "translate-en_ru-1_9.zip"; ExternalSize: 218000000; Hash: "591d743ae103752b88ffc38785c50421320f4eff93c8967e0d3d2e14d4e27811"; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://argos-net.com/v1/translate-ru_en-1_9.argosmodel"; DestDir: "{app}\data"; DestName: "translate-ru_en-1_9.zip"; ExternalSize: 174000000; Hash: "e9ba8bf722d10a4a4c39f74289d5938fd47eac08dbe4ed0afd22d89445a5c3ac"; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"; DestDir: "{app}\data"; DestName: "vosk-model-small-en-us-0.15.zip"; ExternalSize: 71000000; Hash: "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"; DestDir: "{app}\data"; DestName: "vosk-model-small-ru-0.22.zip"; ExternalSize: 92000000; Hash: "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://argos-net.com/v1/translate-de_en-1_9.argosmodel"; DestDir: "{app}\data"; DestName: "translate-de_en-1_9.zip"; ExternalSize: 317000000; Hash: "4de45bb5801c25cf7d776c075c8eb71fac0667d5c9164c0dd9a38b06eaa5f20e"; Tasks: german; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip"; DestDir: "{app}\data"; DestName: "vosk-model-spk-0.4.zip"; ExternalSize: 15000000; Hash: "a74d8f51144484813e16af689bb0f916b7a111e2347f467c4933c1166097b5a7"; Tasks: speakers; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "cublas.zip"; ExternalSize: 1200000000; Hash: "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/c7/bd/1d6709d2223e99f04079f16005f8ae6e11a14ee16b5eab6833686cf72fe1/nvidia_cudnn_cu12-9.28.1.4-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "cudnn.zip"; ExternalSize: 1500000000; Hash: "3467aafa9b260e6adf5fbbfc0e21d180133305b42032aa1160be2d3142bb8b09"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "https://files.pythonhosted.org/packages/52/de/823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl"; DestDir: "{app}\_internal"; DestName: "nvrtc.zip"; ExternalSize: 160000000; Hash: "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"; Tasks: nvidia; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"

[Run]
Filename: "{app}\LiveTranslate.exe"; Description: "Запустить LiveTranslate"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var OldPath: String;
begin
  Result := True;
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C1AD0775-5F30-4C86-9D6B-708E44F090A2}_is1', 'InstallLocation', OldPath) then
    MsgBox('Обнаружена версия, установленная для текущего пользователя. Новая версия будет установлена в Program Files. Прежняя версия останется на месте; ваши личные данные будут скопированы в папку «Документы\LiveTranslate» при запуске новой версии.', mbInformation, MB_OK);
end;
