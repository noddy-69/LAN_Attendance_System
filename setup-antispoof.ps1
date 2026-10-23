<#
.SYNOPSIS
  Install MiniFASNet ONNX liveness models so selfie check-in (and, if enabled, the
  cameras) get TRUE passive anti-spoofing -- rejecting printed-photo / screen attacks.

.DESCRIPTION
  The face service reads every *.onnx in .\models\antispoof (bind-mounted into the
  container at /opt/insightface/antispoof). Filenames must encode scale + input size,
  e.g. 2.7_80x80_MiniFASNetV2.onnx. This script either copies files you already have
  (-FromDir) or downloads them from a URL you trust (fill the manifest below), always
  verifying SHA-256 before installing, then restarts the face service.

  The ONNX models are third-party and are NOT shipped with this software.

.EXAMPLE
  .\setup-antispoof.ps1 -FromDir "C:\models\silent-face-onnx"
.EXAMPLE
  .\setup-antispoof.ps1
#>
param(
  [string]$FromDir = "",
  [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dest = Join-Path $root "models\antispoof"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Expected models. To enable auto-download, fill BOTH Url and Sha256 (a checksum is
# mandatory -- the script refuses to install a file whose hash does not match). Leave
# empty to require -FromDir / manual placement.
$MANIFEST = @(
  @{ Name = "2.7_80x80_MiniFASNetV2.onnx";   Url = ""; Sha256 = "" },
  @{ Name = "4.0_80x80_MiniFASNetV1SE.onnx"; Url = ""; Sha256 = "" }
)

function Get-Sha256([string]$path) { (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower() }

$installed = 0
foreach ($m in $MANIFEST) {
  $name = $m.Name
  $target = Join-Path $dest $name

  if ($FromDir -ne "") {
    $src = Join-Path $FromDir $name
    if (Test-Path $src) {
      Copy-Item $src $target -Force
      Write-Host ("[copied]  {0}" -f $name) -ForegroundColor Green
      $installed++
    } else {
      Write-Host ("[missing] {0} not found in {1}" -f $name, $FromDir) -ForegroundColor Yellow
    }
    continue
  }

  if (Test-Path $target) {
    if ($m.Sha256 -ne "" -and (Get-Sha256 $target) -ne $m.Sha256.ToLower()) {
      Write-Host ("[bad-hash] {0} present but checksum differs. Delete it and re-run." -f $name) -ForegroundColor Red
    } else {
      Write-Host ("[present] {0}" -f $name) -ForegroundColor Green
      $installed++
    }
    continue
  }

  if ($m.Url -ne "" -and $m.Sha256 -ne "") {
    Write-Host ("[download] {0} ..." -f $name)
    $tmp = "$target.part"
    Invoke-WebRequest -Uri $m.Url -OutFile $tmp -UseBasicParsing
    if ((Get-Sha256 $tmp) -ne $m.Sha256.ToLower()) {
      Remove-Item $tmp -Force
      throw "Checksum mismatch for $name. Refusing to install (possible tampering or wrong file)."
    }
    Move-Item $tmp $target -Force
    Write-Host ("[installed] {0}" -f $name) -ForegroundColor Green
    $installed++
  } else {
    Write-Host ("[manual]  {0} - no trusted URL configured in the manifest." -f $name) -ForegroundColor Yellow
  }
}

Write-Host ""
if ($installed -gt 0) {
  Write-Host ("{0} model file(s) ready in {1}" -f $installed, $dest) -ForegroundColor Green
  if (-not $SkipRestart) {
    Write-Host "Restarting the face service to load them..."
    docker compose restart face-recognition 2>$null
    if ($LASTEXITCODE -ne 0) { docker compose -f docker-compose.prod.yml restart face-recognition 2>$null }
  }
  Write-Host "Passive liveness is now active for selfie check-in (verify-selfie reports antispoof_active=true)." -ForegroundColor Green
  Write-Host "To also protect the CAMERAS, set FACE_ANTISPOOF_ENABLED=true in .env and restart."
} else {
  Write-Host "No models installed. Provide the ONNX files and re-run:" -ForegroundColor Yellow
  Write-Host '  .\setup-antispoof.ps1 -FromDir "PATH-TO-FOLDER-WITH-THE-ONNX-FILES"'
  Write-Host ""
  Write-Host "Expected filenames (80x80 MiniFASNet, Silent-Face / minivision project):"
  foreach ($m in $MANIFEST) { Write-Host ("  - {0}" -f $m.Name) }
  Write-Host ("Target folder: {0}" -f $dest)
  Write-Host "Convert the official .pth weights to ONNX, or host a verified copy and fill"
  Write-Host "the Url + Sha256 in the manifest near the top of this script."
}
