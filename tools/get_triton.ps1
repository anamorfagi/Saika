# Installs Triton into the build runtime (ASCII only - see get_triton.txt).
#
# Two traps this script has already stepped on, do not undo:
#  1) UTF-8 without BOM: PowerShell 5.1 reads .ps1 in the system codepage,
#     Cyrillic turns into mojibake and the parser dies. Hence ASCII + BOM.
#  2) $ErrorActionPreference = "Stop": PowerShell turns ANY stderr output of
#     a native program into a terminating error. "import triton" prints a
#     traceback when Triton is absent - which is the normal case here - and
#     the script died on its own probe. So: Continue, and check $LASTEXITCODE
#     by hand.
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot
$cands = @(
  (Join-Path $here "runtime\python.exe"),
  (Join-Path (Split-Path -Parent $here) "build\ANAMORF-0.1.1\runtime\python.exe"),
  (Join-Path (Split-Path -Parent $here) ".venv\Scripts\python.exe"),
  (Join-Path $here "..\runtime\python.exe")
)
$py = $null
foreach ($c in $cands) { if (Test-Path $c) { $py = (Resolve-Path $c).Path; break } }
if (-not $py) { Write-Host "python not found next to this script"; exit 1 }
Write-Host "python: $py"

$null = & $py -c "import triton" 2>&1
if ($LASTEXITCODE -eq 0) {
  $v = & $py -c "import triton; print(triton.__version__)" 2>&1
  Write-Host "Triton already installed: $v"
  exit 0
}
Write-Host "Triton is missing - installing (about 50 MB)..."

# The build runtime is an EMBEDDED python: it ships without pip, and
# ensurepip is not there either ("No module named pip" - seen 23.08.2026).
# A wheel is just a zip, so when pip is absent we unpack it ourselves.
$sp = Join-Path (Split-Path -Parent $py) "Lib\site-packages"
$whl = $null
foreach ($w in @(
    (Join-Path (Split-Path -Parent $here) "third_party\wheels\triton_windows.whl"),
    (Join-Path $here "third_party\wheels\triton_windows.whl"),
    (Join-Path $here "triton_windows.whl"))) {
  if (Test-Path $w) { $whl = (Resolve-Path $w).Path; break }
}

$null = & $py -m pip --version 2>&1
if ($LASTEXITCODE -eq 0) {
  & $py -m pip install --upgrade --no-warn-script-location triton-windows 2>&1 |
    ForEach-Object { Write-Host $_ }
} elseif ($whl) {
  Write-Host "no pip here - unpacking the wheel directly: $whl"
  & $py -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2]); print('unpacked')" $whl $sp 2>&1 |
    ForEach-Object { Write-Host $_ }
} else {
  Write-Host "no pip and no wheel next to the build - nothing to install from"
}

$null = & $py -c "import triton" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "Install failed. Voice stays on whole-phrase synthesis: smooth, but slow."
  exit 1
}
$v = & $py -c "import triton; print(triton.__version__)" 2>&1
Write-Host ""
Write-Host "OK, Triton $v"
Write-Host "Restart ANAMORF: the clone voice will start compiling kernels."
