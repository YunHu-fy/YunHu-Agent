$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$androidDir = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$apk = Join-Path $PSScriptRoot 'downloads/termux-v0.118.3-arm64.apk'
$expected = '72fdb596045116bf5ba1b5bdf5b26fddb9acc0bd074ad9f2da9eb0ae85e83a4e'
if ((Get-FileHash $apk -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Official APK SHA-256 mismatch' }
$assetDir = Join-Path $androidDir 'app/src/main/assets/termux'
$jniDir = Join-Path $androidDir 'app/src/main/jniLibs/arm64-v8a'
New-Item -ItemType Directory -Path $assetDir,$jniDir -Force | Out-Null
$archive = [System.IO.Compression.ZipFile]::OpenRead($apk)
try {
  [System.IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry('lib/arm64-v8a/libtermux.so'), (Join-Path $jniDir 'libtermux.so'), $true)
  $entry = $archive.GetEntry('lib/arm64-v8a/libtermux-bootstrap.so')
  $memory = New-Object System.IO.MemoryStream
  $inputStream = $entry.Open()
  try { $inputStream.CopyTo($memory) } finally { $inputStream.Dispose() }
  $blob = $memory.ToArray()
  $memory.Dispose()
  # The ELF's blob[] is the complete ordinary zip loaded by TermuxInstaller.getZip().
  $start = -1
  $end = -1
  for ($i=0; $i -lt $blob.Length-4; $i++) {
    if ($blob[$i] -eq 80 -and $blob[$i+1] -eq 75) {
      if ($start -lt 0 -and $blob[$i+2] -eq 3 -and $blob[$i+3] -eq 4) { $start=$i }
      if ($start -ge 0 -and $blob[$i+2] -eq 5 -and $blob[$i+3] -eq 6) {
        $candidate = $i + 22 + [BitConverter]::ToUInt16($blob,$i+20)
        $cdOffset = [BitConverter]::ToUInt32($blob,$i+16)
        if ($candidate -le $blob.Length -and $blob[$start+$cdOffset] -eq 80 -and $blob[$start+$cdOffset+1] -eq 75) { $end=$candidate; break }
      }
    }
  }
  if ($start -lt 0 -or $end -lt 0) { throw 'No valid embedded bootstrap zip located' }
  $zipBytes = New-Object byte[] ($end-$start)
  [Array]::Copy($blob,$start,$zipBytes,0,$zipBytes.Length)
  $zipPath = Join-Path $assetDir 'bootstrap-aarch64.zip'
  [System.IO.File]::WriteAllBytes($zipPath,$zipBytes)
  $bootstrap = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
  try {
    $bootstrap.Entries | Select-Object -First 8 FullName,Length
    foreach ($name in @('SYMLINKS.txt','etc/termux/bootstrap/termux-bootstrap-second-stage.sh','etc/profile')) {
      $e = $bootstrap.GetEntry($name)
      if ($e) {
        $out = Join-Path $PSScriptRoot ('downloads/'+($name -replace '/','_'))
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e,$out,$true)
      }
    }
    $bootstrap.Entries | Where-Object { $_.FullName -match '(^bin/(bash|pkg|apt|curl|setsid)|copyright$)' } | Select-Object FullName,Length
  } finally { $bootstrap.Dispose() }
  Get-FileHash $zipPath,(Join-Path $jniDir 'libtermux.so') -Algorithm SHA256 | Format-List
} finally { $archive.Dispose() }
