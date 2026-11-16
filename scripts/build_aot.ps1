[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$FlutterRoot,
    [Parameter(Mandatory = $true)][string]$InstalledFlClashPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

# Build Dart AOT only. This script never stops, installs, or modifies FlClash.
# The target is FlClash v0.8.93 with Flutter 3.41.9 / its matching engine.
$ErrorActionPreference = 'Stop'
$engineRevision = '42d3d75a56efe1a2e9902f52dc8006099c45d937'

function Resolve-ExistingDirectory([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    if (-not $item.PSIsContainer) { throw "Expected a directory: $Path" }
    return $item.FullName
}

function Require-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return [System.IO.Path]::GetFullPath($Path)
}

$sourceRoot = Resolve-ExistingDirectory $SourcePath
$sdkRoot = Resolve-ExistingDirectory $FlutterRoot
$installedRoot = Resolve-ExistingDirectory $InstalledFlClashPath
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)

$sdkEngine = (Get-Content -LiteralPath (Require-File (Join-Path $sdkRoot 'bin\internal\engine.version')) -Raw).Trim()
if ($sdkEngine -ne $engineRevision) {
    throw 'Use Flutter 3.41.9 with the pinned FlClash 0.8.93 engine.'
}

$aotRuntime = Require-File (Join-Path $sdkRoot 'bin\cache\dart-sdk\bin\dartaotruntime.exe')
$frontend = Require-File (Join-Path $sdkRoot 'bin\cache\dart-sdk\bin\snapshots\frontend_server_aot.dart.snapshot')
$patchedSdk = Resolve-ExistingDirectory (Join-Path $sdkRoot 'bin\cache\artifacts\engine\common\flutter_patched_sdk_product')
$genSnapshot = Require-File (Join-Path $sdkRoot 'bin\cache\artifacts\engine\windows-x64-release\gen_snapshot.exe')
$sdkDll = Require-File (Join-Path $sdkRoot 'bin\cache\artifacts\engine\windows-x64-release\flutter_windows.dll')
$installedDll = Require-File (Join-Path $installedRoot 'flutter_windows.dll')
$installedCore = Require-File (Join-Path $installedRoot 'FlClashCore.exe')
$packageConfig = Require-File (Join-Path $sourceRoot '.dart_tool\package_config.json')
$lockFile = Require-File (Join-Path $sourceRoot 'pubspec.lock')
$registrant = Require-File (Join-Path $sourceRoot '.dart_tool\flutter_build\dart_plugin_registrant.dart')
$bridge = Require-File (Join-Path $sourceRoot 'lib\common\control_bridge.dart')

$sdkDllHash = (Get-FileHash -LiteralPath $sdkDll -Algorithm SHA256).Hash
$installedDllHash = (Get-FileHash -LiteralPath $installedDll -Algorithm SHA256).Hash
if ($sdkDllHash -ne $installedDllHash) {
    throw 'The installed Flutter engine differs from the pinned SDK. Do not combine these binaries.'
}

$pubspec = Get-Content -LiteralPath (Require-File (Join-Path $sourceRoot 'pubspec.yaml')) -Raw
if ($pubspec -notmatch '(?m)^version:\s*0\.8\.93(?:\+[^\r\n]+)?\s*$') {
    throw 'Source must target FlClash 0.8.93.'
}
$application = Get-Content -LiteralPath (Require-File (Join-Path $sourceRoot 'lib\application.dart')) -Raw
if ($application -notmatch 'ControlBridge\(' -or $application -notmatch 'enableControlBridge') {
    throw 'Apply the GUI lifecycle integration patch before building.'
}

$coreHash = (Get-FileHash -LiteralPath $installedCore -Algorithm SHA256).Hash.ToLowerInvariant()
$runName = 'build-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDirectory = Join-Path $outputRoot $runName
New-Item -ItemType Directory -Path $runDirectory | Out-Null
$dill = Join-Path $runDirectory 'app-enabled.dill'
$depfile = Join-Path $runDirectory 'kernel-enabled.d'
$registrantUri = ([uri]::new($registrant)).AbsoluteUri

# Passing the ordinary -D arguments directly avoids Flutter assemble's
# dart-define parsing path. gen_snapshot receives relative filenames below:
# the pinned Windows binary otherwise mishandles some non-ASCII absolute paths.
$frontendArguments = @(
    $frontend,
    '--sdk-root', $patchedSdk,
    '--target=flutter',
    '--no-print-incremental-dependencies',
    '-DAPP_ENV=stable',
    "-DCORE_SHA256=$coreHash",
    '-DFLCLASH_CONTROL=true',
    '-Ddart.vm.profile=false',
    '-Ddart.vm.product=true',
    '--delete-tostring-package-uri=dart:ui',
    '--delete-tostring-package-uri=package:flutter',
    '--aot', '--tfa', '--target-os', 'windows',
    '--packages', $packageConfig,
    '--output-dill', $dill,
    '--depfile', $depfile,
    '--source', $registrantUri,
    '--source', 'package:flutter/src/dart_plugin_registrant.dart',
    "-Dflutter.dart_plugin_registrant=$registrantUri",
    '--verbosity=error',
    'package:fl_clash/main.dart'
)
Push-Location -LiteralPath $sourceRoot
try {
    & $aotRuntime @frontendArguments
    if ($LASTEXITCODE -ne 0) { throw 'Dart frontend compilation failed.' }
} finally {
    Pop-Location
}
Require-File $dill | Out-Null

Push-Location -LiteralPath $runDirectory
try {
    & $genSnapshot '--deterministic' '--snapshot_kind=app-aot-elf' '--elf=app-enabled.so' '--strip' 'app-enabled.dill'
    if ($LASTEXITCODE -ne 0) { throw 'Dart AOT snapshot generation failed.' }
} finally {
    Pop-Location
}

$artifact = Require-File (Join-Path $runDirectory 'app-enabled.so')
$artifactBytes = [System.IO.File]::ReadAllBytes($artifact)
$artifactText = [System.Text.Encoding]::UTF8.GetString($artifactBytes)
$wideArtifactText = [System.Text.Encoding]::Unicode.GetString($artifactBytes)
$requiredMarkers = @('flclash-gui-control', 'gui-bridge.json', 'gui-persistent', 'native_action_failed', 'ControlBridge')
foreach ($marker in $requiredMarkers) {
    if (-not $artifactText.Contains($marker) -and -not $wideArtifactText.Contains($marker)) {
        throw "Compiled bridge marker is missing: $marker. Do not install this artifact."
    }
}

$sourceHashes = @{}
foreach ($relativePath in @('lib\common\control_bridge.dart', 'lib\common\proxy.dart', 'lib\core\controller.dart', 'lib\core\interface.dart', 'lib\manager\proxy_manager.dart', 'lib\providers\action.dart', 'lib\application.dart', 'pubspec.lock')) {
    $sourceHashes[$relativePath] = (Get-FileHash -LiteralPath (Join-Path $sourceRoot $relativePath) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest = [ordered]@{
    target = 'FlClash 0.8.93 windows-x64 GUI control bridge'
    flutter_version = '3.41.9'
    engine_revision = $engineRevision
    engine_sha256 = $sdkDllHash.ToLowerInvariant()
    core_sha256 = $coreHash
    artifact = $artifact
    artifact_sha256 = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    artifact_bytes = $artifactBytes.Length
    bridge_markers_verified = $true
    source_sha256 = $sourceHashes
    installation_performed = $false
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDirectory 'build-manifest.json') -Encoding utf8
Write-Output "Verified AOT artifact: $artifact"
Write-Output "Build manifest: $(Join-Path $runDirectory 'build-manifest.json')"
