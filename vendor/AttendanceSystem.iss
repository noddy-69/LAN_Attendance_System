; ════════════════════════════════════════════════════════════════════════════
; Attendance System — Windows installer (Inno Setup).
;
; HOW TO BUILD THE .exe (vendor, one time per release):
;   1. Run  vendor\package.ps1   → creates the  dist\  folder (images + config).
;   2. Install Inno Setup (free): https://jrsoftware.org/isdl.php
;   3. Open THIS file in Inno Setup → Build → Compile.
;      Output: vendor\Output\AttendanceSystem-Setup.exe   (~2 GB — it bundles all images)
;
; WHAT THE OFFICE DOES:
;   Double-click AttendanceSystem-Setup.exe → it loads the images, starts the
;   system, drops an "Open Attendance System" icon on the desktop, and adds the
;   tray launcher to startup. No Docker commands, no pulling, no building.
;   (Docker Desktop must be installed first — the installer checks and warns.)
; ════════════════════════════════════════════════════════════════════════════

#define AppName "Attendance System"
#define AppVer  "1.0.0"

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Your Company
DefaultDirName={autopf}\AttendanceSystem
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputBaseFilename=AttendanceSystem-Setup
OutputDir=Output
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Files]
; Bundle the entire delivery folder produced by vendor\package.ps1
Source: "..\dist\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; For everyone — just opens the web app in the browser:
Name: "{commondesktop}\Open Attendance System"; Filename: "http://localhost"
Name: "{group}\Open Attendance System"; Filename: "http://localhost"
; For the admin — the tray launcher (Start / Stop / Open / Status / Back up):
Name: "{group}\Attendance Launcher"; Filename: "wscript.exe"; Parameters: """{app}\Attendance-Launcher.vbs"""; WorkingDir: "{app}"
Name: "{group}\Stop Attendance System"; Filename: "{app}\stop-attendance.bat"; WorkingDir: "{app}"
; Auto-run the tray launcher at login (containers themselves auto-start via Docker):
Name: "{commonstartup}\Attendance Launcher"; Filename: "wscript.exe"; Parameters: """{app}\Attendance-Launcher.vbs"""; WorkingDir: "{app}"

[Run]
; First run: load the images and start the system (no console window).
Filename: "{cmd}"; Parameters: "/c ""installer-firstrun.bat"""; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "Loading images and starting the system (first run can take several minutes)..."
; Launch the tray launcher now.
Filename: "wscript.exe"; Parameters: """{app}\Attendance-Launcher.vbs"""; WorkingDir: "{app}"; Flags: nowait runhidden
; Offer to open the web app on the finish page.
Filename: "http://localhost"; Flags: shellexec nowait postinstall skipifsilent; Description: "Open Attendance System now"

[UninstallRun]
; Stop the stack when uninstalling (does not delete data volumes).
Filename: "{cmd}"; Parameters: "/c cd /d ""{app}"" && docker compose -f docker-compose.prod.yml down"; Flags: runhidden; RunOnceId: "StopStack"

[Code]
function DockerInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf}\Docker\Docker\Docker Desktop.exe'))
         or FileExists(ExpandConstant('{pf}\Docker\Docker\Docker Desktop.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not DockerInstalled() then
  begin
    if MsgBox('Docker Desktop was not found. The Attendance System needs it to run.' + #13#10 +
              'Install Docker Desktop (free) from:' + #13#10 +
              '    https://www.docker.com/products/docker-desktop' + #13#10 +
              'reboot, then run this installer again.' + #13#10#13#10 +
              'Continue anyway?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
