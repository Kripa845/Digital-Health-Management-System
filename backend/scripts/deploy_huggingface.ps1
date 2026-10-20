# Uploads the backend to a Hugging Face Space (Docker SDK), which then rebuilds and restarts.
# Uploaded from this computer, not GitHub, because ml/symptom_model.joblib is not in git.
# Only changed files are sent, so later runs are quick.
#
# One-time setup (from backend/):
#   .\venv\Scripts\pip install huggingface_hub
#   .\venv\Scripts\hf auth login          # paste a token with "write" access
# Then, each deploy:
#   .\scripts\deploy_huggingface.ps1 -Space your-username/merocarecard-api
param([Parameter(Mandatory = $true)][string]$Space)
$ErrorActionPreference = "Stop"

$Backend = Split-Path $PSScriptRoot -Parent
$Hf = Join-Path $Backend "venv\Scripts\hf.exe"
if (-not (Test-Path $Hf)) { $Hf = "hf" }

if (-not (Test-Path (Join-Path $Backend "ml\symptom_model.joblib"))) {
    throw "ml\symptom_model.joblib is missing: train it first (python -m ml.train_model)."
}

# Local-only files (secrets, databases, environments, training data) never leave this computer.
$Exclude = @(
    "venv/*", "*__pycache__*", "*.pyc", ".pytest_cache/*", ".env", "*.sqlite3",
    "media/*", "e2e-media/*", "staticfiles/*", "deploy/*",
    "ml/data/ddxplus/*", "ml/data/train/*", "ml/data/test/*"
)
$ExcludeArgs = $Exclude | ForEach-Object { "--exclude"; $_ }
& $Hf upload $Space $Backend . --repo-type space --commit-message "Deploy backend" @ExcludeArgs
if ($LASTEXITCODE -ne 0) { throw "Upload failed." }

# The Space's README holds its settings (Docker SDK, port).
& $Hf upload $Space (Join-Path $Backend "deploy\huggingface\README.md") README.md --repo-type space --commit-message "Space settings"
if ($LASTEXITCODE -ne 0) { throw "Upload of the Space README failed." }

$Url = "https://" + ($Space -replace "/", "-").ToLower().Replace("_", "-").Replace(".", "-") + ".hf.space"
"Uploaded. The Space is rebuilding (a few minutes): https://huggingface.co/spaces/$Space"
"API address once running: $Url"
