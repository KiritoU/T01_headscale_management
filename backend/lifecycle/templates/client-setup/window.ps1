# Tailscale Installation and Connection Script for Windows (prompt auth key at runtime)
# This script installs Tailscale (if not present) and connects by asking for auth key after launch.
# Usage: .\window.ps1

$ErrorActionPreference = "Stop"

# Trap to catch all errors and keep window open
trap {
    Write-Host ""
    Write-Error "An error occurred: $_"
    Write-Error "Error details: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) {
        Write-Error "Stack trace: $($_.ScriptStackTrace)"
    }
    Write-Host ""
    Write-Host "Closing in 20 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 20
    exit 1
}

# Optional custom login server
$LOGIN_SERVER = "https://headscale.ovncr.vn"

# Runtime auth key (prompted)
$AUTH_KEY = ""

# Logging functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Exit-WithError {
    param([string]$Message)
    if ($Message) {
        Write-Error $Message
    }
    Write-Host ""
    Write-Host "Closing in 20 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 20
    exit 1
}

function Test-PowerShellVersion {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Exit-WithError "PowerShell 5.1 or higher is required. Current version: $($PSVersionTable.PSVersion)"
    }
    Write-Info "PowerShell version: $($PSVersionTable.PSVersion)"
}

function Test-Administrator {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Exit-WithError "This script must be run as Administrator"
    }
    Write-Info "Running with Administrator privileges"
}

function Test-TailscaleInstalled {
    if (Get-Command tailscale -ErrorAction SilentlyContinue) {
        return $true
    }

    $service = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
    if ($service) {
        return $true
    }

    $regPath = "HKLM:\SOFTWARE\Tailscale"
    if (Test-Path $regPath) {
        return $true
    }

    return $false
}

function Update-SessionPath {
    try {
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $parts = @()
        if (-not [string]::IsNullOrEmpty($machinePath)) { $parts += $machinePath }
        if (-not [string]::IsNullOrEmpty($userPath)) { $parts += $userPath }
        if ($parts.Count -gt 0) { $env:Path = $parts -join ";" }
    } catch {
        Write-Warn "Could not refresh PATH from registry: $_"
    }
}

function Ensure-TailscaleInPath {
    Update-SessionPath
    if (Get-Command tailscale -ErrorAction SilentlyContinue) { return $true }
    $knownPaths = @(
        "${env:ProgramFiles}\Tailscale",
        "${env:ProgramFiles(x86)}\Tailscale"
    )
    foreach ($dir in $knownPaths) {
        $exe = Join-Path $dir "tailscale.exe"
        if (Test-Path $exe) {
            $env:Path = $dir + ";" + $env:Path
            Write-Info "Added Tailscale to PATH: $dir"
            return $true
        }
    }
    return $false
}

function Install-TailscaleWithWinget {
    Write-Info "Attempting to install Tailscale using winget..."
    try {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Warn "winget is not available"
            return $false
        }
        winget install --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
        Write-Info "Tailscale installed successfully using winget"
        return $true
    } catch {
        Write-Warn "Failed to install using winget: $_"
        return $false
    }
}

function Install-TailscaleWithInstaller {
    Write-Info "Downloading Tailscale installer..."

    $installerUrl = "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe"
    $installerPath = "$env:TEMP\tailscale-setup.exe"

    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Info "Installer downloaded to $installerPath"
        Write-Info "Installing Tailscale (this may take a moment)..."
        $process = Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait -PassThru

        if ($process.ExitCode -eq 0) {
            Write-Info "Tailscale installed successfully"
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            return $true
        } else {
            Write-Error "Installer exited with code: $($process.ExitCode)"
            return $false
        }
    } catch {
        Write-Error "Failed to download or install Tailscale: $_"
        return $false
    }
}

function Install-Tailscale {
    Write-Info "Installing Tailscale..."
    if (Install-TailscaleWithWinget) { return }
    if (Install-TailscaleWithInstaller) { return }
    Exit-WithError "Failed to install Tailscale using both methods"
}

function Wait-ForTailscaleService {
    Write-Info "Waiting for Tailscale service to be ready..."

    $maxAttempts = 30
    $attempt = 0

    while ($attempt -lt $maxAttempts) {
        $service = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
        if ($service -and $service.Status -eq "Running") {
            Write-Info "Tailscale service is running"
            return
        }
        Start-Sleep -Seconds 2
        $attempt++
    }

    Write-Warn "Tailscale service may not be ready yet, but continuing..."
}

function Enable-TailscaleService {
    Write-Info "Ensuring Tailscale service is enabled..."

    $service = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
    if ($service) {
        if ($service.StartType -ne "Automatic") {
            Set-Service -Name "Tailscale" -StartupType Automatic
            Write-Info "Tailscale service set to start automatically"
        } else {
            Write-Info "Tailscale service is already set to start automatically"
        }
        if ($service.Status -ne "Running") {
            Start-Service -Name "Tailscale"
            Write-Info "Tailscale service started"
        }
    } else {
        Write-Warn "Tailscale service not found. It may start after installation."
    }
}

function Validate-LoginServer {
    if ([string]::IsNullOrWhiteSpace($LOGIN_SERVER)) {
        Write-Info "No custom login server specified, will use default Tailscale server"
        return
    }
    if (-not ($LOGIN_SERVER -match "^https?://")) {
        Exit-WithError "Invalid login server URL format. URL should start with http:// or https://"
    }
    Write-Info "Login server validated: $LOGIN_SERVER"
}

function Prompt-AuthKey {
    while ($true) {
        $inputKey = Read-Host "Nhap auth key Headscale/Tailscale"
        if ([string]::IsNullOrWhiteSpace($inputKey)) {
            Write-Warn "Auth key khong duoc de trong. Vui long nhap lai."
            continue
        }
        $script:AUTH_KEY = $inputKey.Trim()
        break
    }
}

function Disconnect-Tailscale {
    Write-Info "Checking current Tailscale connection status..."
    if (-not (Ensure-TailscaleInPath)) { return }
    if (Get-Command tailscale -ErrorAction SilentlyContinue) {
        try {
            $statusOutput = & tailscale status 2>&1
            if ($LASTEXITCODE -eq 0 -and $statusOutput) {
                $firstLine = ($statusOutput -split "`n")[0]
                if ($firstLine -match "^\d+\.\d+\.\d+\.\d+") {
                    Write-Warn "Tailscale is already connected. Disconnecting to switch account..."
                    & tailscale down 2>&1 | Out-Null
                    Start-Sleep -Seconds 2
                    Write-Info "Stopping Tailscale service..."
                    Stop-Service -Name "Tailscale" -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 2
                    Write-Info "Removing Tailscale state files to fully reset connection..."
                    $statePath = "$env:ProgramData\Tailscale\tailscaled.state"
                    if (Test-Path $statePath) { Remove-Item $statePath -Force -ErrorAction SilentlyContinue }
                    Start-Service -Name "Tailscale" -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 3
                }
            }
        } catch {
            Write-Info "Tailscale appears to be disconnected"
        }
    }
}

function Connect-Tailscale {
    Write-Info "Connecting to Tailscale..."
    Disconnect-Tailscale

    if (-not (Ensure-TailscaleInPath)) {
        Exit-WithError "tailscale command not found. Please restart your PowerShell session or add Tailscale to PATH."
    }

    try {
        if (-not [string]::IsNullOrWhiteSpace($LOGIN_SERVER)) {
            Write-Info "Using custom login server: $LOGIN_SERVER"
            & tailscale up --force-reauth --login-server=$LOGIN_SERVER --authkey=$AUTH_KEY --accept-routes --accept-dns
        } else {
            Write-Info "Using default Tailscale server"
            & tailscale up --force-reauth --authkey=$AUTH_KEY --accept-routes --accept-dns
        }

        if ($LASTEXITCODE -eq 0) {
            Write-Info "Successfully connected to Tailscale!"
            Write-Info "Tailscale status:"
            & tailscale status
        } else {
            $errorMsg = "Failed to connect to Tailscale. Exit code: $LASTEXITCODE`n"
            if (-not [string]::IsNullOrWhiteSpace($LOGIN_SERVER)) {
                $errorMsg += "Please check your login server URL and auth key and try again"
            } else {
                $errorMsg += "Please check your auth key and try again"
            }
            Exit-WithError $errorMsg
        }
    } catch {
        Exit-WithError "Error connecting to Tailscale: $_"
    }
}

function Main {
    Write-Info "Starting Tailscale installation and connection script (prompt auth key mode)..."

    Test-PowerShellVersion
    Test-Administrator

    if (Test-TailscaleInstalled) {
        Write-Info "Tailscale is already installed"
    } else {
        Install-Tailscale
    }

    Enable-TailscaleService
    Wait-ForTailscaleService
    if (-not (Ensure-TailscaleInPath)) {
        Exit-WithError "Tailscale appears installed but tailscale command is not found. Please restart PowerShell and run this script again."
    }
    Validate-LoginServer
    Prompt-AuthKey
    Connect-Tailscale

    Write-Info "Script completed successfully!"
}

try {
    Main
} catch {
    Write-Error "An error occurred: $_"
    Write-Error "Error details: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) {
        Write-Error "Stack trace: $($_.ScriptStackTrace)"
    }
    Write-Host ""
    Write-Host "Closing in 20 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 20
    exit 1
}

Write-Host ""
Write-Host "Closing in 20 seconds..." -ForegroundColor Green
Start-Sleep -Seconds 20
