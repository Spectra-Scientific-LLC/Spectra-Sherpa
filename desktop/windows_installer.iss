[Setup]
AppName=Spectra Sherpa
; Preserve the historical default AppId (= AppName), including upgrade/uninstall identity.
AppId=Spectra Sherpa
AppVersion={#AppVersionString}
AppVerName=Spectra Sherpa {#AppVersionString}
AppPublisher=Spectra Scientific LLC
AppCopyright=Copyright (C) 2026 Spectra Scientific LLC. All rights reserved.
SetupIconFile=electron\assets\logo.ico
AppPublisherURL=https://spectrascientific.ai/
AppSupportURL=https://spectrascientific.ai/
AppUpdatesURL=https://spectrascientific.ai/
DefaultDirName={autopf}\SpectraSherpa
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=SpectraSherpa_Setup
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={app}\SpectraSherpa.exe
AppMutex=Global\SpectraSherpaAppMutex
CloseApplications=yes
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
#ifdef NativeShell
Source: "electron\out\SpectraSherpa-win32-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
Source: "dist\SpectraSherpa\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

#endif

#ifdef NativeShell
[UninstallDelete]
; Electron's runtime folder (Chromium cache and state). The window uses an
; in-memory session, so it holds no user data; always remove it.
Type: filesandordirs; Name: "{userappdata}\Spectra Sherpa"
#endif

[Icons]
Name: "{autoprograms}\Spectra Sherpa"; Filename: "{app}\SpectraSherpa.exe"
Name: "{autodesktop}\Spectra Sherpa"; Filename: "{app}\SpectraSherpa.exe"; Tasks: desktopicon

[Code]
var
  DataDir: String;

procedure InitializeWizard();
begin
  DataDir := ExpandConstant('{%USERPROFILE}\.spectra_sherpa');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if DirExists(ExpandConstant('{%USERPROFILE}\.spectra_sherpa')) then
    begin
      if not UninstallSilent() then
      begin
        if MsgBox('Do you want to delete your Spectra Sherpa data (projects, datasets, models, results, logs, backups and saved API keys) in ' + ExpandConstant('{%USERPROFILE}\.spectra_sherpa') + '?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        begin
          DelTree(ExpandConstant('{%USERPROFILE}\.spectra_sherpa'), True, True, True);
        end;
      end;
    end;
  end;
end;
