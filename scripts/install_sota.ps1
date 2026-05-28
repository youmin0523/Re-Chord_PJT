# scripts/install_sota.ps1 — one-shot SOTA-deps installer for Re:Chord.
#
# Installs every optional accuracy-boosting dependency the platform can
# use. Each step is idempotent (re-runs are safe) and isolated (a failure
# in one package doesn't abort the rest — we surface the failures at the
# end as a summary).
#
# Usage:
#   pwsh ./scripts/install_sota.ps1
#
# Expected runtime: 15-30 minutes on a fresh env (most of it tensorflow
# wheels + LLM model pull).

param(
    [switch] $SkipLLM,        # skip Ollama download + model pull
    [switch] $SkipPiano,      # skip transkun piano transcription
    [switch] $Verbose
)

$ErrorActionPreference = "Continue"
$results = @{}

function Try-Step {
    param([string]$Name, [scriptblock]$Block)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    try {
        & $Block
        $results[$Name] = "OK"
        Write-Host "[$Name] OK" -ForegroundColor Green
    } catch {
        $results[$Name] = "FAILED: $_"
        Write-Host "[$Name] FAILED: $_" -ForegroundColor Yellow
    }
}

# 1) Light deps — pyworld + huggingface-hub.
Try-Step "pyworld + huggingface-hub" {
    uv pip install pyworld huggingface-hub
}

# 2) CREPE (needs --no-build-isolation because of pkg_resources legacy).
Try-Step "crepe (bass / monophonic SOTA)" {
    uv pip install setuptools
    uv pip install crepe --no-build-isolation
}

# 3) CREMA chord recognizer.
Try-Step "crema (170-class chord SOTA)" {
    uv pip install crema
}

# 4) Transkun piano polyphonic (optional, py3.11-compatible alternative
#    to omnizart which caps at py3.10).
if (-not $SkipPiano) {
    Try-Step "transkun (piano polyphonic SOTA)" {
        uv pip install transkun
    }
}

# 5) Ollama + small instruct model for LLM-based re-ranking.
if (-not $SkipLLM) {
    Try-Step "ollama windows portable" {
        $bin = Join-Path $PSScriptRoot "..\bin"
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        $ollamaDir = Join-Path $bin "ollama"
        if (-not (Test-Path (Join-Path $ollamaDir "ollama.exe"))) {
            $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/ollama/ollama/releases/latest" -Headers @{ "User-Agent" = "rechord" }
            $asset = $rel.assets | Where-Object { $_.name -eq "ollama-windows-amd64.zip" } | Select-Object -First 1
            if (-not $asset) { throw "no windows-amd64 asset in latest release" }
            $zip = Join-Path $bin "ollama.zip"
            Write-Host "  downloading $($asset.browser_download_url)…"
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $ollamaDir -Force
            Remove-Item $zip
        }
        $exe = (Get-ChildItem $ollamaDir -Recurse -Filter "ollama.exe" | Select-Object -First 1).FullName
        Write-Host "  ollama at $exe"
    }

    Try-Step "ollama: llama3.2:1b model pull" {
        $exe = (Get-ChildItem (Join-Path $PSScriptRoot "..\bin\ollama") -Recurse -Filter "ollama.exe" | Select-Object -First 1).FullName
        # Start ollama serve in background if not already running.
        $running = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
        if (-not $running) {
            Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden
            Start-Sleep -Seconds 3
        }
        & $exe pull llama3.2:1b
    }
}

# Summary.
Write-Host "`n=== SUMMARY ===" -ForegroundColor Cyan
$results.GetEnumerator() | Sort-Object Key | ForEach-Object {
    $color = if ($_.Value -eq "OK") { "Green" } else { "Yellow" }
    Write-Host ("  {0,-40} {1}" -f $_.Key, $_.Value) -ForegroundColor $color
}
