; Inno Setup script for Continuum.
; Produces Continuum-Setup.exe: installs the app, shortcuts and uninstaller,
; and (optionally) installs Ollama for the user if it isn't already present.
;
; Build steps:
;   1) python packaging\build.py          (creates dist\Continuum.exe)
;   2) Install Inno Setup 6.1+ from https://jrsoftware.org/isinfo.php
;   3) Open this file in Inno Setup and click Compile (or: iscc packaging\installer.iss)
;   Output: packaging\Output\Continuum-Setup.exe
;
; The app's Python dependencies are already inside Continuum.exe (PyInstaller).
; The only external dependency is Ollama (the local model runtime); the task
; below downloads and silently installs it. Models are downloaded in-app.

#define MyAppName "Continuum"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "KpiFinity Inc."
#define MyAppExeName "Continuum.exe"
#define OllamaUrl "https://ollama.com/download/OllamaSetup.exe"

[Setup]
AppId={{8E5F0B2A-9C7D-4E3A-9B1F-CONTINUUM0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Continuum-Setup
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install needs no admin; switch to admin if installing to Program Files.
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "ollama"; Description: "Install Ollama (the local AI engine Continuum needs) if it isn't already installed"; GroupDescription: "Dependencies:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OllamaInstalled(): Boolean;
begin
  { Ollama installs per-user by default; also check Program Files. }
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'))
         or FileExists(ExpandConstant('{autopf}\Ollama\ollama.exe'))
         or FileExists(ExpandConstant('{userappdata}\..\Local\Programs\Ollama\ollama.exe'));
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(
    'Installing Ollama',
    'Downloading the local AI engine so Continuum can run models on your computer.',
    nil);
end;

function ShouldInstallOllama(): Boolean;
begin
  Result := WizardIsTaskSelected('ollama') and (not OllamaInstalled());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and ShouldInstallOllama() then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#OllamaUrl}', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if DownloadPage.AbortedByUser then
          Log('Ollama download aborted by user.')
        else
          SuppressibleMsgBox('Could not download Ollama automatically. ' +
            'You can install it later from https://ollama.com.' + #13#10 +
            'Continuum will still install.', mbInformation, MB_OK, IDOK);
        Result := True;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and ShouldInstallOllama()
     and FileExists(ExpandConstant('{tmp}\OllamaSetup.exe')) then
  begin
    { OllamaSetup.exe is itself an Inno Setup installer: /SILENT runs it quietly. }
    Exec(ExpandConstant('{tmp}\OllamaSetup.exe'),
         '/SILENT /SUPPRESSMSGBOXES /NORESTART', '',
         SW_SHOW, ewWaitUntilTerminated, ResultCode);
  end;
end;
