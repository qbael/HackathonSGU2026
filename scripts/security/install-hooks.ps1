# Install pre-commit hook for Windows PowerShell
$hookSource = Join-Path $PSScriptRoot "pre-commit"
$hookTarget = Join-Path (Get-Item $PSScriptRoot).Parent.Parent.FullName ".git\hooks\pre-commit"

if (Test-Path (Split-Path $hookTarget)) {
    [System.IO.File]::WriteAllText($hookTarget, [System.IO.File]::ReadAllText($hookSource))
    Write-Host "✅ Pre-commit hook installed to $hookTarget"
} else {
    Write-Error "Not a git repository or .git/hooks directory not found."
}
