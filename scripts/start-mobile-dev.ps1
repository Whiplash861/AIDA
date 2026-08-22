param(
    [switch]$ClearMetro
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $repoRoot "mobile"
$envFile = Join-Path $mobileRoot ".env.local"
$gatewayPort = 8787
$gatewayProcess = $null

function Resolve-Python {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Resolve-LanIPv4 {
    $candidates = Get-NetIPConfiguration |
        Where-Object {
            $_.IPv4DefaultGateway -ne $null -and
            $_.NetAdapter.Status -eq "Up"
        } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Where-Object {
            $_ -and
            $_ -notlike "127.*" -and
            $_ -notlike "169.254.*"
        }

    $address = $candidates | Select-Object -First 1
    if (-not $address) {
        throw "No active LAN IPv4 address was found. Connect the PC and test device to the same network."
    }
    return $address
}

function Wait-GatewayReady([string]$url) {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        try {
            return Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "AIDA Services Gateway did not become ready within 20 seconds."
}

Set-Location $repoRoot
$python = Resolve-Python
$lanIp = Resolve-LanIPv4
$token = & $python -c "import secrets; print(secrets.token_urlsafe(32))"
$token = ($token | Out-String).Trim()
if (-not $token) {
    throw "Failed to generate an ephemeral AIDA development gateway token."
}

$gatewayUrl = "http://${lanIp}:$gatewayPort"
$localGatewayUrl = "http://127.0.0.1:$gatewayPort"

# Expo only exposes EXPO_PUBLIC values to the JavaScript bundle. These are
# ephemeral development credentials written to an ignored .env.local file and
# are never committed or used by release builds.
@"
EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL=$gatewayUrl
EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN=$token
"@ | Set-Content -Path $envFile -Encoding utf8

$env:AIDA_SERVICES_GATEWAY_TOKEN = $token
$env:AIDA_SERVICES_GATEWAY_HOST = "0.0.0.0"
$env:AIDA_SERVICES_GATEWAY_PORT = "$gatewayPort"

Write-Host ""
Write-Host "AIDA Mobile Development" -ForegroundColor Cyan
Write-Host "Gateway: $gatewayUrl"
Write-Host "Enrollment: automatic for this development session"
Write-Host ""

try {
    $gatewayProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "aida.services_gateway") `
        -WorkingDirectory $repoRoot `
        -PassThru

    $health = Wait-GatewayReady $localGatewayUrl
    Write-Host "Gateway reasoning configured: $($health.reasoning_configured)"
    Write-Host "Gateway speech configured:    $($health.speech_configured)"

    Set-Location $mobileRoot

    if (-not (Test-Path (Join-Path $mobileRoot "node_modules\expo-audio"))) {
        Write-Host "Installing updated mobile dependencies..." -ForegroundColor Yellow
        npm install
    }

    npm run sync-aida-assets
    npm run typecheck

    if ($ClearMetro) {
        npx expo start --clear
    }
    else {
        npx expo start
    }
}
finally {
    if ($gatewayProcess -and -not $gatewayProcess.HasExited) {
        Stop-Process -Id $gatewayProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $envFile -Force -ErrorAction SilentlyContinue
    Set-Location $repoRoot
}
