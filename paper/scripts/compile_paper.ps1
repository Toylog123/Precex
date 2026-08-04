$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$paperRoot = [IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$manuscriptDir = Join-Path $paperRoot "manuscript"
$buildDir = Join-Path $paperRoot "build"
$source = "precex_paper.tex"
$builtPdf = Join-Path $buildDir "precex_paper.pdf"
$releasePdf = Join-Path $paperRoot "precex_paper.pdf"

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

Push-Location $manuscriptDir
try {
    & latexmk -g -xelatex -interaction=nonstopmode -halt-on-error -outdir="$buildDir" $source
    if ($LASTEXITCODE -ne 0) {
        throw "latexmk failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Copy-Item -LiteralPath $builtPdf -Destination $releasePdf -Force
Write-Host "LaTeX build complete: $releasePdf" -ForegroundColor Green
