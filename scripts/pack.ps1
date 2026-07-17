#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$Out
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path $Root).Path.TrimEnd('\')
$outDir = Split-Path $Out -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
$Out = (Resolve-Path $outDir).Path + '\' + (Split-Path $Out -Leaf)

$excludeDirs = @(
    '.venv',
    '.git',
    '__pycache__',
    '.pytest_cache',
    'build',
    'dist',
    '.cursor'
)

$excludeFilePatterns = @(
    '*_result_*.csv',
    '*.pyc',
    '*.pyo',
    '*.zip',
    '.DS_Store',
    'Thumbs.db'
)

$staging = Join-Path $env:TEMP ("evb-comm-tool-pack-{0}" -f [guid]::NewGuid().ToString('N'))
$bundleRoot = Join-Path $staging 'evb-comm-tool'
New-Item -ItemType Directory -Path $bundleRoot | Out-Null

try {
    $files = Get-ChildItem -Path $Root -Recurse -File -Force | Where-Object {
        $rel = $_.FullName.Substring($Root.Length + 1)
        $parts = $rel -split '\\'

        foreach ($part in $parts[0..([Math]::Max(0, $parts.Length - 2))]) {
            if ($excludeDirs -contains $part) { return $false }
        }

        foreach ($pattern in $excludeFilePatterns) {
            if ($_.Name -like $pattern) { return $false }
        }

        return $true
    }

    if ($files.Count -eq 0) {
        Write-Error "No files to pack under $Root"
        exit 1
    }

    foreach ($file in $files) {
        $rel = $file.FullName.Substring($Root.Length + 1)
        $dest = Join-Path $bundleRoot $rel
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
    }

    if (Test-Path $Out) {
        Remove-Item -LiteralPath $Out -Force
    }

    Compress-Archive -Path $bundleRoot -DestinationPath $Out -CompressionLevel Optimal
    Write-Host ("Packed {0} files -> {1}" -f $files.Count, $Out)
}
finally {
    if (Test-Path $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
