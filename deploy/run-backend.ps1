# Re:Chord backend — persistent uvicorn.
# Launched at logon by the "ReChord Backend" scheduled task so the API
# survives a reboot / terminal close. Reads .env via pydantic-settings
# (CORS_ALLOW_ORIGINS, RECHORD_OPS_TOKEN, OPENAI_API_KEY, ...).
$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root
& "$root\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7860
