<#
.SYNOPSIS
  Enable browser-trusted HTTPS using a free DuckDNS subdomain + a Let's Encrypt
  certificate (DNS-01), with NOTHING to install on any phone. HTTPS is needed only
  for the phone selfie check-in (camera access).

.DESCRIPTION
  Run once on the host PC with -Domain + -DuckToken. It:
    1. Points your DuckDNS subdomain's A record at this PC's LAN IP.
    2. Gets a Let's Encrypt cert via DNS-01 using the pure-PowerShell Posh-ACME
       module + its DuckDNS plugin (no Python/certbot).
    3. Installs it as nginx\certs\attendance.crt/.key, switches the app to HTTPS
       (.env: DEPLOYMENT_MODE=local-ssl, BASE_URL=https://<domain>), restarts nginx.
    4. Saves the DuckDNS settings (token encrypted with Windows DPAPI) and registers
       a scheduled task that runs AT LOGON and DAILY to:
         - re-point DuckDNS to the current LAN IP (handles DHCP IP changes), and
         - renew the certificate when it is within 30 days of expiry.

  After the one-time setup you NEVER run this manually again - reboots and IP changes
  are handled automatically by the scheduled task.

  Prerequisites: a free DuckDNS account (https://www.duckdns.org) and internet access.

.EXAMPLE
  .\setup-https.ps1 -Domain youroffice -DuckToken 1a2b3c4d-5e6f -Email admin@acme.com

.EXAMPLE
  .\setup-https.ps1 -Sync        # what the scheduled task runs; update IP + renew if due
#>
param(
  [string]$Domain,
  [string]$DuckToken,
  [string]$LanIp = "",
  [string]$Email = "",
  [switch]$Staging,
  [switch]$Sync,
  [switch]$Renew,      # alias of -Sync (kept for back-compat)
  [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root    = $PSScriptRoot
$certDir = Join-Path $root "nginx\certs"
$envFile = Join-Path $root ".env"
$cfgFile = Join-Path $root ".https-config.json"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

function Info($m) { Write-Host "[*]  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Die($m)  { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

function Get-LanIp {
  # The real LAN adapter is the one that is Up AND has a default gateway. This
  # excludes Docker/WSL/Hyper-V virtual adapters (e.g. 172.x with no gateway).
  $cands = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
           Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' }
  $ips = @($cands | ForEach-Object { $_.IPv4Address.IPAddress })
  $pick = $ips | Where-Object { $_ -like '192.168.*' } | Select-Object -First 1
  if (-not $pick) { $pick = $ips | Where-Object { $_ -like '10.*' } | Select-Object -First 1 }
  if (-not $pick) { $pick = $ips | Select-Object -First 1 }
  return $pick
}

function New-NetConnectTrigger {
  # An "on event" trigger that fires the moment a network connects (Wi-Fi join,
  # reconnect after sleep/drop, or reboot) — Windows logs event 10000 in
  # Microsoft-Windows-NetworkProfile/Operational. The task then runs -Sync, so the
  # DuckDNS A record self-heals within seconds of a DHCP IP change, mid-session.
  $cls = Get-CimClass -Namespace ROOT\Microsoft\Windows\TaskScheduler -ClassName MSFT_TaskEventTrigger
  $t = New-CimInstance -CimClass $cls -ClientOnly
  $t.Enabled = $true
  $t.Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[Provider[@Name=''Microsoft-Windows-NetworkProfile''] and EventID=10000]]</Select></Query></QueryList>'
  return $t
}

function Save-Config($fqdn, $sub, $token) {
  # Token encrypted with DPAPI (current user + machine). Only this user/PC can read it.
  $enc = (ConvertTo-SecureString $token -AsPlainText -Force) | ConvertFrom-SecureString
  [pscustomobject]@{ Fqdn = $fqdn; Sub = $sub; TokenEnc = $enc } |
    ConvertTo-Json | Set-Content $cfgFile -Encoding ascii
}

function Read-Config {
  if (-not (Test-Path $cfgFile)) { return $null }
  $c = Get-Content $cfgFile -Raw | ConvertFrom-Json
  $sec = $c.TokenEnc | ConvertTo-SecureString
  $tok = (New-Object System.Management.Automation.PSCredential('x', $sec)).GetNetworkCredential().Password
  [pscustomobject]@{ Fqdn = $c.Fqdn; Sub = $c.Sub; Token = $tok }
}

function Update-DuckIp($sub, $token, $ip) {
  $u = "https://www.duckdns.org/update?domains=$sub&token=$token&ip=$ip"
  $body = (Invoke-WebRequest -Uri $u -UseBasicParsing).Content
  # Windows PowerShell 5.1 sometimes returns the body as a byte[] (which has no
  # .Trim()); decode it to text so this works on both PS 5.1 and PS 7.
  if ($body -is [byte[]]) { $body = [System.Text.Encoding]::ASCII.GetString($body) }
  return (([string]$body).Trim() -eq "OK")
}

function Copy-Certs($cert) {
  Copy-Item $cert.FullChainFile (Join-Path $certDir "attendance.crt") -Force
  Copy-Item $cert.KeyFile        (Join-Path $certDir "attendance.key") -Force
}

function Restart-Nginx {
  if ($NoRestart) { return }
  Push-Location $root
  # Recreate (not just restart): switching DEPLOYMENT_MODE to local-ssl changes which
  # conf file is bind-mounted (local.conf -> local-ssl.conf). A plain 'restart' keeps
  # the container's original mounts, so nginx would never start listening on 443.
  try { docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx | Out-Null } catch {} finally { Pop-Location }
}

function Install-CertIfChanged($cert) {
  # Only copy + restart nginx when the certificate actually changed (e.g. after a
  # renewal) - so the daily sync doesn't restart nginx for nothing.
  $dst = Join-Path $certDir "attendance.crt"
  $changed = $true
  if (Test-Path $dst) { $changed = (Get-FileHash $cert.FullChainFile).Hash -ne (Get-FileHash $dst).Hash }
  if ($changed) { Copy-Certs $cert; Restart-Nginx }
  return $changed
}

function Ensure-PoshAcme {
  if (-not (Get-Module -ListAvailable -Name Posh-ACME)) {
    Info "Installing Posh-ACME (one time, from the PowerShell Gallery)..."
    if (-not (Get-PackageProvider -ListAvailable -Name NuGet -ErrorAction SilentlyContinue)) {
      Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    }
    Install-Module Posh-ACME -Scope CurrentUser -Force -AllowClobber
  }
  Import-Module Posh-ACME
}

function Set-HttpsEnv($fqdn) {
  # Switch .env to HTTPS mode. Returns $true if .env exists and was updated.
  if (-not (Test-Path $envFile)) { return $false }
  $c = Get-Content $envFile
  if ($c -match '^DEPLOYMENT_MODE=') { $c = $c -replace '^DEPLOYMENT_MODE=.*','DEPLOYMENT_MODE=local-ssl' } else { $c += 'DEPLOYMENT_MODE=local-ssl' }
  if ($c -match '^BASE_URL=')        { $c = $c -replace '^BASE_URL=.*',"BASE_URL=https://$fqdn" }          else { $c += "BASE_URL=https://$fqdn" }
  $c | Set-Content $envFile -Encoding ascii
  return $true
}

function Ensure-HttpsMode($fqdn) {
  # Self-heal: if .env lost the HTTPS mode (e.g. it was regenerated to defaults by
  # start-attendance.bat), restore it and reload nginx - so HTTPS survives a .env
  # regeneration WITHOUT re-running the full setup. No-op when already correct.
  if (-not (Test-Path $envFile)) { return }
  if ((Get-Content $envFile) -match '^DEPLOYMENT_MODE=local-ssl\s*$') { Info "HTTPS mode OK."; return }
  [void](Set-HttpsEnv $fqdn)
  Restart-Nginx
  Ok "HTTPS mode was missing from .env (regenerated?) - restored and reloaded nginx."
}

function Ensure-MediamtxHostIp($ip) {
  # Keep mediamtx's advertised WebRTC host IP (HOST_LAN_IP in .env) in sync with the
  # current LAN IP so the in-app webcam survives DHCP changes. Recreates mediamtx only
  # when the IP actually changed. No-op when .env / mediamtx aren't present.
  if (-not $ip) { return }
  if (-not (Test-Path $envFile)) { return }
  $lines = Get-Content $envFile
  $line = ($lines | Where-Object { $_ -match '^HOST_LAN_IP=' } | Select-Object -First 1)
  $current = if ($line) { ($line -replace '^HOST_LAN_IP=','').Trim() } else { '' }
  if ($current -eq $ip) { return }   # already correct
  if ($lines -match '^HOST_LAN_IP=') { $lines = $lines -replace '^HOST_LAN_IP=.*', "HOST_LAN_IP=$ip" } else { $lines += "HOST_LAN_IP=$ip" }
  $lines | Set-Content $envFile -Encoding ascii
  if ($NoRestart) { return }
  Push-Location $root
  try { docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate mediamtx | Out-Null } catch {} finally { Pop-Location }
  Ok "Webcam (mediamtx) host IP updated -> $ip"
}

Ensure-PoshAcme
Set-PAServer ($(if ($Staging) { 'LE_STAGE' } else { 'LE_PROD' }))

# ── Sync mode (run by the scheduled task at logon/daily) ─────────────────────────
if ($Sync -or $Renew) {
  $cfg = Read-Config
  if (-not $cfg) { Die "No saved HTTPS config (.https-config.json). Run the full setup first." }

  # Restore HTTPS mode in .env first (survives a regenerated .env), then refresh IP + cert.
  Ensure-HttpsMode $cfg.Fqdn

  $ip = if ($LanIp) { $LanIp } else { Get-LanIp }
  if ($ip) {
    if (Update-DuckIp $cfg.Sub $cfg.Token $ip) { Ok "DuckDNS A record refreshed -> $ip" }
    else { Info "DuckDNS IP update did not return OK." }
    Ensure-MediamtxHostIp $ip
  } else { Info "No LAN IP detected; skipped DuckDNS IP refresh." }

  Submit-Renewal | Out-Null
  $cert = Get-PACertificate
  if ($cert) {
    if (Install-CertIfChanged $cert) { Ok "Certificate renewed and reloaded." }
    else { Info "Certificate still current; no renewal needed." }
  }
  return
}

# ── Full one-time setup ──────────────────────────────────────────────────────────
if (-not $Domain)    { Die "Provide -Domain (your DuckDNS subdomain, e.g. 'youroffice')." }
if (-not $DuckToken) { Die "Provide -DuckToken (from your DuckDNS account page)." }

$fqdn = if ($Domain -like "*.duckdns.org") { $Domain } else { "$Domain.duckdns.org" }
$sub  = $fqdn -replace '\.duckdns\.org$',''

if (-not $LanIp) {
  $LanIp = Get-LanIp
  if (-not $LanIp) { Die "Could not auto-detect a LAN IP. Re-run with -LanIp 192.168.x.x" }
}
Info "Domain : $fqdn"
Info "LAN IP : $LanIp"

Info "Pointing $fqdn -> $LanIp via DuckDNS..."
if (-not (Update-DuckIp $sub $DuckToken $LanIp)) { Die "DuckDNS update failed. Check the subdomain and token." }
Ok "DuckDNS A record set."

Info "Requesting a Let's Encrypt certificate (DNS-01, this can take 1-2 minutes)..."
# The DuckDNS plugin needs BOTH the token and the subdomain(s) to set the TXT
# record; omitting DuckDomain makes Posh-ACME stop and prompt for it interactively.
$pArgs = @{
  DuckToken  = (ConvertTo-SecureString $DuckToken -AsPlainText -Force)
  DuckDomain = @($sub)
}
$paParams = @{ Domain = $fqdn; Plugin = 'DuckDNS'; PluginArgs = $pArgs; AcceptTOS = $true; Force = $true }
if ($Email) { $paParams.Contact = $Email }
$cert = New-PACertificate @paParams
Copy-Certs $cert
Ok "Certificate installed into nginx\certs."

if (Set-HttpsEnv $fqdn) {
  Ok ".env switched to HTTPS (DEPLOYMENT_MODE=local-ssl, BASE_URL=https://$fqdn)"
} else {
  Info "No .env yet - after the first run set DEPLOYMENT_MODE=local-ssl and BASE_URL=https://$fqdn"
}

# Recreate the backend FIRST (new BASE_URL for notification/email links), THEN nginx -
# so nginx resolves the freshly recreated backend's IP and we avoid a transient 502 from
# a stale upstream. Proof/avatar images are origin-relative and don't depend on BASE_URL.
if (-not $NoRestart) {
  Push-Location $root
  try { docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate backend | Out-Null } catch {} finally { Pop-Location }
}
Restart-Nginx
Save-Config $fqdn $sub $DuckToken

# Register the auto-updater: AT LOGON (reboots) + DAILY (always-on PCs) + ON NETWORK
# CONNECT (instant self-heal when the Wi-Fi/IP changes mid-session).
try {
  $scriptPath = $MyInvocation.MyCommand.Path
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" -Sync"
  $trigs   = @(
    (New-ScheduledTaskTrigger -AtLogOn),
    (New-ScheduledTaskTrigger -Daily -At 3am),
    (New-NetConnectTrigger)
  )
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
               -LogonType Interactive -RunLevel Highest
  Unregister-ScheduledTask -TaskName "AttendanceHTTPSRenew" -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName "AttendanceHTTPS" -Action $action -Trigger $trigs `
    -Principal $principal -Force | Out-Null
  Ok "Auto-updater scheduled (logon + daily + on every network reconnect): refreshes the IP and renews the cert."
} catch {
  Info "Could not register the auto-updater task: $($_.Exception.Message)"
  Info "You can re-run '.\setup-https.ps1 -Sync' manually if the IP changes."
}

Write-Host ""
Ok "HTTPS is ready. On the office Wi-Fi, open:  https://$fqdn"
Write-Host "    Nothing to install on phones. Use the domain, not the bare IP." -ForegroundColor Yellow
Write-Host "    You do NOT need to re-run this after reboots - the scheduled task keeps it current." -ForegroundColor Yellow
Write-Host "    If a phone cannot reach it, your router may block 'DNS rebinding' -- whitelist $fqdn once." -ForegroundColor Yellow
