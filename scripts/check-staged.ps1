$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$scanner = Get-Command gitleaks -ErrorAction SilentlyContinue
if ($scanner) {
    $executable = $scanner.Source
} else {
    $executable = Join-Path $root 'data\publish-tools\gitleaks.exe'
    if (-not (Test-Path -LiteralPath $executable)) { throw 'Install Gitleaks before publishing.' }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $env:PATH = (Join-Path $root 'data\mingit\cmd') + ';' + $env:PATH
}
& $executable git --staged --redact --no-banner $root
exit $LASTEXITCODE
