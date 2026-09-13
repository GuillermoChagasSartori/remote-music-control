; Inno Setup script for the Remote Music Control installer. Run through packaging\build.ps1.
;
; Inno Setup reads this description and produces one setup .exe that installs
; the PyInstaller folder, adds Start menu entries, an uninstaller, the firewall
; rule and (optionally) start at logon. The installer speaks English or
; Portuguese, chosen from the Windows language.
;
; build.ps1 passes the version on the command line: /DAppVersion=0.9.0
;
; Saved as UTF-8 with a byte order mark (BOM), so Inno Setup reads the
; Portuguese accents correctly whatever the PC's language settings.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z installer.iss
#endif

#define AppName "Remote Music Control"
#define AppExe "RemoteMusicControl.exe"
#define FirewallRule "Remote Music Control"

[Setup]
; AppId identifies the product to Windows forever: an installer with the same
; AppId updates the existing installation instead of adding a second one.
; Never change it.
AppId={{6F3A2E1D-8B47-4C59-9E2A-3D5B7C1F4A86}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Guillermo Chagas Sartori
AppPublisherURL=https://github.com/GuillermoChagasSartori/remote-music-control
; Program Files, for every user; administrator rights are needed for that and
; for the firewall rule (ADR 0015).
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
SetupArchitecture=x64
OutputDir=..\dist
OutputBaseFilename=RemoteMusicControl-Setup-{#AppVersion}
SetupIconFile=..\src\remote_music_control\app\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The app holds this mutex while it runs (app/single_instance.py). Setup and
; the uninstaller see it and ask the user to close the app first, so files in
; use are never half-replaced.
AppMutex=RemoteMusicControl.Instance
; Windows 10 version 1809 or later: the oldest with WebView2 support we rely on.
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
english.StartAtLogon=Start Remote Music Control when I sign in to Windows
brazilianportuguese.StartAtLogon=Iniciar o Remote Music Control quando eu entrar no Windows
english.DesktopShortcut=Create a desktop shortcut
brazilianportuguese.DesktopShortcut=Criar um atalho na área de trabalho
english.InstallingWebView2=Installing Microsoft WebView2 (needed to show YouTube Music)...
brazilianportuguese.InstallingWebView2=Instalando o Microsoft WebView2 (necessário para mostrar o YouTube Music)...
english.WebView2Failed=Microsoft WebView2 could not be installed. Remote Music Control needs it to show YouTube Music. Connect to the internet and run this installer again, or install "WebView2 Runtime" from Microsoft's website.
brazilianportuguese.WebView2Failed=Não foi possível instalar o Microsoft WebView2. O Remote Music Control precisa dele para mostrar o YouTube Music. Conecte-se à internet e execute este instalador de novo, ou instale o "WebView2 Runtime" pelo site da Microsoft.
english.RemoveUserData=Also delete your settings and your YouTube Music sign-in on this PC?%n%nChoose No to keep them for a future installation (phones stay paired).
brazilianportuguese.RemoveUserData=Apagar também suas configurações e o login do YouTube Music neste PC?%n%nEscolha Não para mantê-los para uma instalação futura (os celulares continuam pareados).
english.LaunchApp=Open Remote Music Control
brazilianportuguese.LaunchApp=Abrir o Remote Music Control

[Tasks]
Name: "startatlogon"; Description: "{cm:StartAtLogon}"
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked

[Files]
; Everything PyInstaller produced. "ignoreversion": always replace on update.
Source: "..\dist\RemoteMusicControl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Microsoft's small WebView2 bootstrapper, extracted to a temporary folder
; only when WebView2 is missing (see NeedsWebView2 below).
Source: "..\build\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[InstallDelete]
; On an update, remove the previous version's bundled files first, so a
; package dropped in the new version doesn't linger next to its replacement.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Start at logon, for every user of this PC, in the tray (--minimized). The
; standard "Run" key; removed by the uninstaller. See ADR 0014 for why this
; replaced the scheduled task.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: startatlogon
; Unticking the task on an update removes an entry left by a previous install.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "{#AppName}"; ValueType: none; Flags: deletevalue; Tasks: not startatlogon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:InstallingWebView2}"; Flags: waituntilterminated; Check: NeedsWebView2; AfterInstall: CheckWebView2Installed
; Firewall: allow the app to receive connections from devices on the local
; network only (remoteip=localsubnet). Deleted first so updates never pile up
; duplicate rules. netsh ships with Windows.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow program=""{app}\{#AppExe}"" protocol=TCP remoteip=localsubnet profile=private,domain"; Flags: runhidden waituntilterminated
; The final page's "Open Remote Music Control" checkbox. runasoriginaluser:
; not as administrator, so the app runs as the user who started setup.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"

[Code]
const
  // The WebView2 runtime's product code, as documented by Microsoft for
  // detecting an installed runtime.
  WebView2ClientKey = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2UserKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Version(): String;
begin
  Result := '';
  if not RegQueryStringValue(HKLM, WebView2ClientKey, 'pv', Result) then
    RegQueryStringValue(HKCU, WebView2UserKey, 'pv', Result);
end;

function NeedsWebView2(): Boolean;
var
  Version: String;
begin
  Version := WebView2Version();
  // Microsoft: a missing value, empty, or "0.0.0.0" all mean "not installed".
  Result := (Version = '') or (Version = '0.0.0.0');
end;

procedure CheckWebView2Installed();
begin
  if NeedsWebView2() then
    MsgBox(CustomMessage('WebView2Failed'), mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // After the files are gone, offer to delete the user's own data too. The
  // default answer is No: keeping it makes reinstalling seamless.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    if MsgBox(CustomMessage('RemoveUserData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\remote-music-control'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\remote-music-control'), True, True, True);
    end;
end;
