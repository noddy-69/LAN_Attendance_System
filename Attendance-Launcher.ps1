# ════════════════════════════════════════════════════════════════════════════
# Attendance System — system-tray launcher.
#
# Shows a tray icon (green = running, red = stopped) with a right-click menu:
#   Open Attendance · Start · Stop · Status · Back up data · Exit
# Double-click the tray icon to open the web app.
#
# Launch it with NO console window via Attendance-Launcher.vbs, or add that .vbs
# to your Startup folder so it appears automatically when you log in.
#
# Runs `docker compose` against the compose file in this same folder
# (prefers docker-compose.prod.yml; falls back to docker-compose.yml).
# ════════════════════════════════════════════════════════════════════════════
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir
$Compose = if (Test-Path (Join-Path $ScriptDir 'docker-compose.prod.yml')) { 'docker-compose.prod.yml' } else { 'docker-compose.yml' }
$Url = 'http://localhost'

function New-DotIcon([System.Drawing.Color]$Color) {
    $bmp = New-Object System.Drawing.Bitmap 16, 16
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $brush = New-Object System.Drawing.SolidBrush $Color
    $g.FillEllipse($brush, 1, 1, 14, 14)
    $brush.Dispose(); $g.Dispose()
    [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}
$IconUp   = New-DotIcon ([System.Drawing.Color]::FromArgb(46, 204, 113))
$IconDown = New-DotIcon ([System.Drawing.Color]::FromArgb(231, 76, 60))
$IconBusy = New-DotIcon ([System.Drawing.Color]::FromArgb(241, 196, 15))

$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = $IconBusy
$ni.Text = 'Attendance System'
$ni.Visible = $true

function Show-Tip([string]$Msg, [string]$Kind = 'Info') {
    $ni.ShowBalloonTip(3000, 'Attendance System', $Msg, ([System.Windows.Forms.ToolTipIcon]$Kind))
}

function Invoke-ComposeAsync([string]$Action) {
    Start-Process -WindowStyle Hidden -FilePath 'powershell' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        "Set-Location '$ScriptDir'; docker compose -f '$Compose' $Action"
    )
}

function Test-Running {
    try { return ((Invoke-WebRequest -Uri "$Url/api/v1/health" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) }
    catch { return $false }
}

function Update-Status {
    if (Test-Running) { $ni.Icon = $IconUp; $ni.Text = 'Attendance System - running' }
    else { $ni.Icon = $IconDown; $ni.Text = 'Attendance System - stopped' }
}

# ── Context menu ────────────────────────────────────────────────────────────
$menu = New-Object System.Windows.Forms.ContextMenuStrip

$mOpen = New-Object System.Windows.Forms.ToolStripMenuItem 'Open Attendance'
$mOpen.add_Click({ Start-Process $Url })
[void]$menu.Items.Add($mOpen)

[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$mStart = New-Object System.Windows.Forms.ToolStripMenuItem 'Start'
$mStart.add_Click({ $ni.Icon = $IconBusy; Show-Tip 'Starting... first start can take ~1 minute.'; Invoke-ComposeAsync 'up -d' })
[void]$menu.Items.Add($mStart)

$mStop = New-Object System.Windows.Forms.ToolStripMenuItem 'Stop'
$mStop.add_Click({ Show-Tip 'Stopping...'; Invoke-ComposeAsync 'down' })
[void]$menu.Items.Add($mStop)

$mStatus = New-Object System.Windows.Forms.ToolStripMenuItem 'Status'
$mStatus.add_Click({
    if (Test-Running) { Show-Tip 'Running - open at http://localhost' 'Info' }
    else { Show-Tip 'Not running. Click Start.' 'Warning' }
})
[void]$menu.Items.Add($mStatus)

$mBackup = New-Object System.Windows.Forms.ToolStripMenuItem 'Back up data'
$mBackup.add_Click({
    $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
    $dir = Join-Path $ScriptDir 'backups'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $out = Join-Path $dir "attendance_$ts.sql"
    Start-Process -WindowStyle Hidden -FilePath 'cmd' -ArgumentList @('/c', "docker compose -f ""$Compose"" exec -T postgres pg_dump -U attendance_user attendance > ""$out""")
    Show-Tip "Backup started -> backups\attendance_$ts.sql"
})
[void]$menu.Items.Add($mBackup)

$mHttps = New-Object System.Windows.Forms.ToolStripMenuItem 'Enable phone HTTPS...'
$mHttps.add_Click({
    $script = Join-Path $ScriptDir 'setup-https.ps1'
    if (-not (Test-Path $script)) { Show-Tip 'setup-https.ps1 not found in this folder.' 'Error'; return }
    $t = 'Enable phone HTTPS'
    $sub = [Microsoft.VisualBasic.Interaction]::InputBox("Your DuckDNS subdomain (create a free one at duckdns.org), e.g. youroffice", $t, '')
    if (-not $sub) { return }
    $tok = [Microsoft.VisualBasic.Interaction]::InputBox("Paste your DuckDNS token", $t, '')
    if (-not $tok) { return }
    $eml = [Microsoft.VisualBasic.Interaction]::InputBox("Email for renewal notices (optional)", $t, '')
    Show-Tip 'Setting up HTTPS... this can take a minute.'
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"", '-Domain', "`"$sub`"", '-DuckToken', "`"$tok`"")
    if ($eml) { $a += @('-Email', "`"$eml`"") }
    Start-Process -FilePath 'powershell' -ArgumentList $a
})
[void]$menu.Items.Add($mHttps)

[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$mExit = New-Object System.Windows.Forms.ToolStripMenuItem 'Exit (leaves system running)'
$mExit.add_Click({ $timer.Stop(); $ni.Visible = $false; $ni.Dispose(); [System.Windows.Forms.Application]::Exit() })
[void]$menu.Items.Add($mExit)

$ni.ContextMenuStrip = $menu
$ni.add_MouseDoubleClick({ Start-Process $Url })

# ── Status polling ──────────────────────────────────────────────────────────
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 15000
$timer.add_Tick({ Update-Status })
$timer.Start()
Update-Status

[System.Windows.Forms.Application]::Run()
