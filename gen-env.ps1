# gen-env.ps1 - fill a freshly-copied .env with the LAN IP and strong random secrets.
# Called by setup-windows.bat as:
#   powershell -NoProfile -ExecutionPolicy Bypass -File gen-env.ps1 -LanIp 192.168.1.2
# Kept in a separate file so there is no cmd.exe quote-escaping to break.

param([string]$LanIp = "192.168.1.100")

# Cryptographic RNG that works on BOTH Windows PowerShell 5.1 (.NET Framework) and
# PowerShell 7 (.NET). The static GetBytes(int) overload only exists on .NET Core,
# so use the instance method which is present everywhere.
function New-Bytes([int]$n) {
  $b = New-Object 'System.Byte[]' $n
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($b) } finally { $rng.Dispose() }
  return ,$b
}
function New-Hex { [System.BitConverter]::ToString((New-Bytes 32)).Replace('-', '').ToLower() }
function New-Pw  { [System.BitConverter]::ToString((New-Bytes 18)).Replace('-', '') }

# Self-detect the real LAN adapter (Up + has a default gateway). This avoids picking
# Docker/WSL/Hyper-V virtual adapters (e.g. 172.x with no gateway). Falls back to the
# value passed in by start-attendance.bat if detection finds nothing.
function Get-LanIp {
  $cands = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
           Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' }
  $ips = @($cands | ForEach-Object { $_.IPv4Address.IPAddress })
  $pick = $ips | Where-Object { $_ -like '192.168.*' } | Select-Object -First 1
  if (-not $pick) { $pick = $ips | Where-Object { $_ -like '10.*' } | Select-Object -First 1 }
  if (-not $pick) { $pick = $ips | Select-Object -First 1 }
  return $pick
}
$detected = Get-LanIp
if ($detected) { $LanIp = $detected }

$dbp = New-Pw
$c = Get-Content '.env'
$c = $c -replace 'BASE_URL=.*',             "BASE_URL=http://$LanIp"
# Host LAN IP for mediamtx WebRTC (in-app webcam) — advertised so the browser can reach
# the media stream. Appended if the .env template doesn't already carry the line.
if ($c -match '^HOST_LAN_IP=') { $c = $c -replace 'HOST_LAN_IP=.*', "HOST_LAN_IP=$LanIp" } else { $c += "HOST_LAN_IP=$LanIp" }
$c = $c -replace 'NEXT_PUBLIC_API_URL=.*',  "NEXT_PUBLIC_API_URL=/api/v1"
$c = $c -replace 'SECRET_KEY=.*',           "SECRET_KEY=$(New-Hex)"
$c = $c -replace 'POSTGRES_PASSWORD=.*',    "POSTGRES_PASSWORD=$dbp"
$c = $c -replace 'DATABASE_URL=.*',         "DATABASE_URL=postgresql+asyncpg://attendance_user:$dbp@postgres:5432/attendance"
$c = $c -replace 'MINIO_SECRET_KEY=.*',     "MINIO_SECRET_KEY=$(New-Pw)"
$c = $c -replace 'SERVICE_ACCOUNT_PASSWORD=.*', "SERVICE_ACCOUNT_PASSWORD=$(New-Pw)"

# ASCII, no BOM - docker compose must be able to read the .env values.
Set-Content -Path '.env' -Value $c -Encoding ascii
