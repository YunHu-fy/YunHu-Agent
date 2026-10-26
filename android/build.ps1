[CmdletBinding()]
param(
    [switch]$BootstrapGradle,
    [switch]$Check,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GradleArguments
)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$gradleVersion = '8.13'
$gradleSha256 = '20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78'

# Change environment only in this process; never change the user's SDK or JDK.
if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME 'bin/java.exe'))) {
    $javaCommand = Get-Command java -ErrorAction Stop
    $env:JAVA_HOME = Split-Path (Split-Path $javaCommand.Source -Parent) -Parent
}
$sdkCandidates = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT,
    (Join-Path $env:LOCALAPPDATA 'Android/Sdk'))
$sdkDir = $sdkCandidates | Where-Object { $_ -and (Test-Path (Join-Path $_ 'platforms/android-36.1/android.jar')) } | Select-Object -First 1
if (-not $sdkDir) {
    throw 'Android SDK platform android-36.1 is required. Set ANDROID_HOME to your SDK. No SDK is downloaded by this script.'
}
if (-not (Test-Path (Join-Path $sdkDir 'build-tools/36.1.0/aapt2.exe'))) {
    throw 'Android SDK build-tools 36.1.0 is required. Install it through Android Studio SDK Manager.'
}
$env:ANDROID_HOME = $sdkDir
$env:ANDROID_SDK_ROOT = $sdkDir
# Some Windows installations contain quoted PATH entries; Java Path rejects them.
$env:Path = (($env:Path -split ';') | ForEach-Object { $_.Trim().Trim([char]34) }) -join ';'
$gradleUserDir = if ($env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME } else { Join-Path $env:USERPROFILE '.gradle' }
$gradleCandidates = @()
$gradleCache = Join-Path $gradleUserDir ('wrapper/dists/gradle-' + $gradleVersion + '-bin')
if (Test-Path $gradleCache) {
    $gradleCandidates += Get-ChildItem -LiteralPath $gradleCache -Filter 'gradle.bat' -File -Recurse | ForEach-Object { $_.FullName }
}
$bootstrapDir = Join-Path $projectDir '.bootstrap'
$localGradle = Join-Path $bootstrapDir ('gradle-' + $gradleVersion + '/bin/gradle.bat')
if (Test-Path $localGradle) { $gradleCandidates += $localGradle }
if (-not $gradleCandidates -and $BootstrapGradle) {
    New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null
    $zipPath = Join-Path $bootstrapDir ('gradle-' + $gradleVersion + '-bin.zip')
    if (-not (Test-Path $zipPath)) {
        Invoke-WebRequest -UseBasicParsing -Uri ('https://downloads.gradle.org/distributions/gradle-' + $gradleVersion + '-bin.zip') -OutFile $zipPath
    }
    $actualHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $gradleSha256) { throw ('Gradle distribution checksum mismatch: ' + $zipPath) }
    Expand-Archive -LiteralPath $zipPath -DestinationPath $bootstrapDir -Force
    $gradleCandidates += $localGradle
}
if (-not $gradleCandidates) {
    throw 'Cached Gradle 8.13 not found. Run build.ps1 -BootstrapGradle to download its verified official distribution, or generate the standard wrapper with installed Gradle 8.13.'
}
$gradleExecutable = $gradleCandidates | Select-Object -First 1
Write-Output ('JAVA_HOME=' + $env:JAVA_HOME)
Write-Output ('ANDROID_HOME=' + $sdkDir)
Write-Output ('GRADLE=' + $gradleExecutable)
if ($Check) {
    & $gradleExecutable --version
    exit $LASTEXITCODE
}
if (-not $GradleArguments -or $GradleArguments.Count -eq 0) {
    $GradleArguments = @(':app:assembleDebug', ':app:lintDebug', '--console=plain', '--no-daemon')
}
& $gradleExecutable --project-dir $projectDir @GradleArguments
exit $LASTEXITCODE
