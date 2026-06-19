# Re:Chord Cloudflare named tunnel — persistent.
# Launched at logon by the "ReChord Tunnel" scheduled task. Routes
# api.youmin.site -> http://127.0.0.1:7860 per ~/.cloudflared/config.yml.
$cloudflared = "C:\Users\Codelab\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
& $cloudflared tunnel run rechord
