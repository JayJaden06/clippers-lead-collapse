<#
.SYNOPSIS
Morning data refresh for the hosted dashboard. Windows Task Scheduler runs it every day
(see install_daily_refresh.ps1).

.DESCRIPTION
Pulls last night's games from stats.nba.com, rebuilds every table, reruns the analysis and the
report, and pushes the result to main. Streamlit Community Cloud redeploys the dashboard from
that push. It runs on this PC rather than on GitHub because stats.nba.com blocks cloud servers.

It is careful with your work:
- it skips (and logs why) if the repo isn't on main or has uncommitted changes;
- it commits only when there's a new game, newly published tracking data, new results
  elsewhere in the league (for the next-game odds) or a change to the injury report for a
  Clippers game, and otherwise throws away the date-only
  changes the rerun makes;
- -DryRun does everything except commit and push, then puts the files back.

Each run writes logs\refresh-YYYY-MM-DD.log.
#>
param([switch]$DryRun)

# Native commands write progress to stderr; with "Stop", Windows PowerShell would treat that as
# a failure. Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("refresh-{0:yyyy-MM-dd}.log" -f (Get-Date))

function Write-Log([string]$msg) {
    $line = "{0:HH:mm:ss} {1}" -f (Get-Date), $msg
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Invoke-Step([string]$label, [string]$exe, [string[]]$argv) {
    Write-Log "> $label"
    $out = & $exe @argv 2>&1 | ForEach-Object { "$_" }
    if ($out) { Add-Content -Path $log -Value $out -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
    return $out
}

function Restore-Data {
    git checkout -- data reports 2>&1 | Out-Null
    git clean -fdq -- data/processed reports 2>&1 | Out-Null
}

$courtside = Join-Path $repo ".venv\Scripts\courtside.exe"
$python = Join-Path $repo ".venv\Scripts\python.exe"

try {
    Write-Log "Refresh started$(if ($DryRun) { ' (dry run)' })"
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if (-not $DryRun -and $branch -ne "main") {
        Write-Log "Skipped: the repo is on branch '$branch', not main. Nothing changed."
        exit 0
    }
    if (git status --porcelain) {
        Write-Log "Skipped: there are uncommitted changes. Nothing changed."
        exit 0
    }
    if (-not $DryRun) { Invoke-Step "git pull" "git" @("pull", "--ff-only") | Out-Null }

    Invoke-Step "courtside all" $courtside @("all") | Out-Null

    # New Clippers games or tracking, other teams' results (league table, schedule) for the next-game odds,
    # roster moves (trades and signings happen on days without games too), or a change to who's on the injury
    # report for a Clippers game (the file is only rewritten when a player or status changes).
    $news = git status --porcelain -- data/processed/games.parquet data/processed/matchups.parquet `
        data/processed/league_periods.parquet data/processed/schedule.parquet `
        data/processed/roster.parquet data/processed/shots.parquet data/processed/player_history_halves.parquet `
        data/processed/injuries.parquet data/processed/game_injuries.parquet
    if (-not $news) {
        Write-Log "No new games, tracking or league results; discarding the rerun's date-only changes."
        Restore-Data
        exit 0
    }
    $last = (& $python -c "import pandas as pd; print(pd.read_parquet('data/processed/games.parquet')['game_date'].max().date())").Trim()
    $message = "Refresh data through $last"
    if ($DryRun) {
        Write-Log "Dry run: would commit '$message' with these files:"
        git status --porcelain -- data reports | ForEach-Object { Write-Log "  $_" }
        Restore-Data
        exit 0
    }
    Invoke-Step "git add" "git" @("add", "data", "reports") | Out-Null
    Invoke-Step "git commit" "git" @("commit", "-m", $message) | Out-Null
    Invoke-Step "git push" "git" @("push") | Out-Null
    Write-Log "Done: committed and pushed '$message'."
}
catch {
    Write-Log "FAILED: $_"
    Restore-Data
    exit 1
}
