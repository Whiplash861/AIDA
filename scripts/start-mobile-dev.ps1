param(
    [switch]$ClearMetro
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $repoRoot "mobile"
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

function Wait-GatewayReady([string]$url, [string]$enrollmentToken) {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        try {
            $enrolled = Invoke-RestMethod -Uri "$url/v1/enroll" -Method Post -Headers @{Authorization = "Bearer $enrollmentToken"} -TimeoutSec 2
            try {
                return Invoke-RestMethod -Uri "$url/v1/ready" -Headers @{Authorization = "Bearer $($enrolled.token)"} -TimeoutSec 2
            }
            finally {
                $null = Invoke-RestMethod -Uri "$url/v1/session" -Method Delete -Headers @{Authorization = "Bearer $($enrolled.token)"} -TimeoutSec 2
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "AIDA Services Gateway did not become ready within 20 seconds."
}

Set-Location $repoRoot
$python = Resolve-Python

# Compile parity-critical Python modules before starting a provider service.
& $python -m compileall -q `
    (Join-Path $repoRoot "aida\services_gateway") `
    (Join-Path $repoRoot "aida\audio\text.py") `
    (Join-Path $repoRoot "aida\intent\technomancer.py") `
    (Join-Path $repoRoot "aida\interaction\transcription.py")
if ($LASTEXITCODE -ne 0) {
    throw "AIDA parity-critical Python modules failed syntax validation."
}

$lanIp = Resolve-LanIPv4
$token = & $python -c "import secrets; print(secrets.token_urlsafe(32))"
$token = ($token | Out-String).Trim()
if (-not $token) {
    throw "Failed to generate an ephemeral AIDA development gateway token."
}

$gatewayUrl = "http://${lanIp}:$gatewayPort"
$localGatewayUrl = "http://127.0.0.1:$gatewayPort"

# Pass development settings only to this launcher and its child processes.
# The user's existing dotenv files remain intact.
$originalDirectory = Get-Location
$environmentNames = @("EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL", "EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN", "AIDA_SERVICES_GATEWAY_TOKEN", "AIDA_SERVICES_GATEWAY_HOST", "AIDA_SERVICES_GATEWAY_PORT")
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
$env:EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL = $gatewayUrl
$env:EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN = $token
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
        -WindowStyle Hidden `
        -PassThru

    $health = Wait-GatewayReady $localGatewayUrl $token
    Write-Host "Gateway intent resolution:       $($health.intent_resolution_configured)"
    Write-Host "Gateway reasoning configured:    $($health.reasoning_configured)"
    Write-Host "Gateway speech configured:       $($health.speech_configured)"
    Write-Host "Gateway transcription configured: $($health.transcription_configured)"

    if (-not $health.transcription_configured) {
        Write-Host "Voice input will remain staged until OPENAI_API_KEY is configured for AIDA transcription." -ForegroundColor Yellow
    }

    Set-Location $mobileRoot

    if (-not (Test-Path -LiteralPath (Join-Path $mobileRoot "node_modules/typescript/bin/tsc"))) {
        Write-Host "Installing locked mobile dependencies..." -ForegroundColor DarkCyan
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "Mobile dependency installation failed." }
    }

    npm run sync-aida-assets
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical AIDA audio asset synchronization failed."
    }

    npm run typecheck
    if ($LASTEXITCODE -ne 0) {
        throw "AIDA Mobile TypeScript validation failed."
    }

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
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process") }
    Set-Location $originalDirectory
}
