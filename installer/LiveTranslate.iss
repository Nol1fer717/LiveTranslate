#ifndef PayloadDir
  #error PayloadDir must point to the prepared application folder
#endif
#ifndef OutputDir
  #error OutputDir must point to the installer output folder
#endif

[Setup]
AppId={{C1AD0775-5F30-4C86-9D6B-708E44F090A2}
AppName=LiveTranslate
AppVersion=1.4.1
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
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"
Name: "german"; Description: "Немецкий язык: перевод в обе стороны (загрузка около 450 МБ)"; Flags: unchecked
Name: "speakers"; Description: "Различать голоса собеседников (загрузка около 50 МБ)"; Flags: unchecked
Name: "nvidia"; Description: "Дополнительно установить ускорение NVIDIA (определяется автоматически)"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "\_internal\nvidia\*,\data\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\model.bin"; DestDir: "{app}\data\whisper-small"; DestName: "model.bin"; ExternalSize: 486197344; Hash: "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"; Check: HasDownload('model.bin'); Flags: external ignoreversion
Source: "{tmp}\downloads\config.json"; DestDir: "{app}\data\whisper-small"; DestName: "config.json"; ExternalSize: 2200; Hash: "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"; Check: HasDownload('config.json'); Flags: external ignoreversion
Source: "{tmp}\downloads\tokenizer.json"; DestDir: "{app}\data\whisper-small"; DestName: "tokenizer.json"; ExternalSize: 2200000; Hash: "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"; Check: HasDownload('tokenizer.json'); Flags: external ignoreversion
Source: "{tmp}\downloads\vocabulary.txt"; DestDir: "{app}\data\whisper-small"; DestName: "vocabulary.txt"; ExternalSize: 500000; Hash: "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"; Check: HasDownload('vocabulary.txt'); Flags: external ignoreversion
Source: "{tmp}\downloads\translate-en_ru-1_9.zip"; DestDir: "{app}\data"; ExternalSize: 218000000; Hash: "591d743ae103752b88ffc38785c50421320f4eff93c8967e0d3d2e14d4e27811"; Check: HasDownload('translate-en_ru-1_9.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\translate-ru_en-1_9.zip"; DestDir: "{app}\data"; ExternalSize: 174000000; Hash: "e9ba8bf722d10a4a4c39f74289d5938fd47eac08dbe4ed0afd22d89445a5c3ac"; Check: HasDownload('translate-ru_en-1_9.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\vosk-model-small-en-us-0.15.zip"; DestDir: "{app}\data"; ExternalSize: 71000000; Hash: "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"; Check: HasDownload('vosk-model-small-en-us-0.15.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\vosk-model-small-ru-0.22.zip"; DestDir: "{app}\data"; ExternalSize: 92000000; Hash: "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"; Check: HasDownload('vosk-model-small-ru-0.22.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\translate-en_de-1_3.zip"; DestDir: "{app}\data"; ExternalSize: 164904507; Hash: "6cd847f0c06c9c66013e6b0932e07fd54a6d90894659c02bf6c5247b72fb25b1"; Tasks: german; Check: HasDownload('translate-en_de-1_3.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\translate-de_en-1_9.zip"; DestDir: "{app}\data"; ExternalSize: 317000000; Hash: "4de45bb5801c25cf7d776c075c8eb71fac0667d5c9164c0dd9a38b06eaa5f20e"; Tasks: german; Check: HasDownload('translate-de_en-1_9.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\vosk-model-spk-0.4.zip"; DestDir: "{app}\data"; ExternalSize: 15000000; Hash: "a74d8f51144484813e16af689bb0f916b7a111e2347f467c4933c1166097b5a7"; Tasks: speakers; Check: HasDownload('vosk-model-spk-0.4.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\speaker-segmentation.onnx"; DestDir: "{app}\data"; ExternalSize: 5992913; Hash: "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"; Tasks: speakers; Check: HasDownload('speaker-segmentation.onnx'); Flags: external ignoreversion
Source: "{tmp}\downloads\wespeaker-resnet34.onnx"; DestDir: "{app}\data"; ExternalSize: 26534365; Hash: "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94"; Tasks: speakers; Check: HasDownload('wespeaker-resnet34.onnx'); Flags: external ignoreversion
Source: "{tmp}\downloads\cublas.zip"; DestDir: "{app}\_internal"; ExternalSize: 1200000000; Hash: "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"; Check: HasDownload('cublas.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\cudnn.zip"; DestDir: "{app}\_internal"; ExternalSize: 1500000000; Hash: "3467aafa9b260e6adf5fbbfc0e21d180133305b42032aa1160be2d3142bb8b09"; Check: HasDownload('cudnn.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\nvrtc.zip"; DestDir: "{app}\_internal"; ExternalSize: 160000000; Hash: "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"; Check: HasDownload('nvrtc.zip'); Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\downloads\turbo-model.bin"; DestDir: "{app}\data\whisper-turbo"; DestName: "model.bin"; ExternalSize: 1617884929; Hash: "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"; Check: HasDownload('turbo-model.bin'); Flags: external ignoreversion
Source: "{tmp}\downloads\turbo-config.json"; DestDir: "{app}\data\whisper-turbo"; DestName: "config.json"; ExternalSize: 2263; Hash: "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e"; Check: HasDownload('turbo-config.json'); Flags: external ignoreversion
Source: "{tmp}\downloads\turbo-tokenizer.json"; DestDir: "{app}\data\whisper-turbo"; DestName: "tokenizer.json"; ExternalSize: 2710337; Hash: "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd"; Check: HasDownload('turbo-tokenizer.json'); Flags: external ignoreversion
Source: "{tmp}\downloads\turbo-vocabulary.json"; DestDir: "{app}\data\whisper-turbo"; DestName: "vocabulary.json"; ExternalSize: 1068114; Hash: "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1"; Check: HasDownload('turbo-vocabulary.json'); Flags: external ignoreversion
Source: "{tmp}\downloads\turbo-preprocessor_config.json"; DestDir: "{app}\data\whisper-turbo"; DestName: "preprocessor_config.json"; ExternalSize: 340; Hash: "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"; Check: HasDownload('turbo-preprocessor_config.json'); Flags: external ignoreversion

[Icons]
Name: "{autoprograms}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"
Name: "{autodesktop}\LiveTranslate"; Filename: "{app}\LiveTranslate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\model_downloader.exe"; Parameters: "{code:BackgroundArgs}"; Flags: nowait
Filename: "{app}\LiveTranslate.exe"; Description: "Запустить LiveTranslate"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\.model-downloads"
Type: filesandordirs; Name: "{app}\_internal\nvidia"

[Code]
function HasDownload(Name: String): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\downloads\' + Name));
end;

function BackgroundArgs(Param: String): String;
var Tasks: String;
begin
  Tasks := '';
  if WizardIsTaskSelected('german') then Tasks := Tasks + 'german,';
  if WizardIsTaskSelected('speakers') then Tasks := Tasks + 'speakers,';
  if WizardIsTaskSelected('nvidia') then Tasks := Tasks + 'nvidia,';
  Result := '--target "' + ExpandConstant('{app}') + '" --output "' + ExpandConstant('{app}\.model-downloads') + '" --auto-gpu --install --tasks "' + Tasks + '"';
  if WizardSilent then Result := Result + ' --silent';
end;

function InitializeSetup(): Boolean;
var OldPath: String;
begin
  Result := True;
  if IsAdminInstallMode and (not WizardSilent) and
     (not RegKeyExists(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C1AD0775-5F30-4C86-9D6B-708E44F090A2}_is1')) and
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C1AD0775-5F30-4C86-9D6B-708E44F090A2}_is1', 'InstallLocation', OldPath) then
    MsgBox('Обнаружена версия, установленная для текущего пользователя. Новая версия будет установлена в Program Files. Прежняя версия останется на месте; ваши личные данные будут скопированы в папку «Документы\LiveTranslate» при запуске новой версии.', mbInformation, MB_OK);
end;
