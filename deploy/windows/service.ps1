<#
.SYNOPSIS
  Blasting Intelligence background server on Windows (scheduled task "Blasting Intelligence").

.DESCRIPTION
  install    checks server.env and the certificate, registers a task that starts the server at boot and
             restarts it within 5 minutes if it stops, opens the firewall port(s) (Domain and Private
             profiles only), restricts data\tls to Administrators / SYSTEM / the service account, starts it.
  uninstall  stops and removes the task and the firewall rules (data, backups and certificates are kept).
  restart    stops and starts the task (after editing server.env or renewing the certificate).
  status     task state, process, and whether the server answers on /api/health.

  Uses only Windows components (Task Scheduler, Windows Firewall); no third-party service wrapper.
  Called by install_service.bat / uninstall_service.bat / service_status.bat in the application folder.
#>
param(
    [ValidateSet("install", "uninstall", "restart", "status")]
    [string]$Action = "status",
    [string]$Account = ""          # e.g. MINE\svc-blasting; empty = local SYSTEM
)

$ErrorActionPreference = "Stop"
$TaskName = "Blasting Intelligence"
$RulePrefix = "Blasting Intelligence"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Root "server.env"

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Fail($text) { Say "ERROR: $text" Red; exit 1 }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Setting([string]$Name, [string]$Default = "") {
    # value from the Windows environment, else server.env, else the default
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ($v) { return $v }
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content -Path $EnvFile -Encoding UTF8) {
            $t = $line.Trim()
            if ($t.StartsWith("#") -or -not $t.Contains("=")) { continue }
            $k, $val = $t.Split("=", 2)
            if ($k.Trim() -eq $Name) { return $val.Trim().Trim('"').Trim("'") }
        }
    }
    return $Default
}

function Invoke-Python([string[]]$PyArgs) {
    Push-Location $Backend
    try {
        $env:BI_MODE = "production"
        & $Python @PyArgs | Out-Host   # shown, not returned: the function returns only the exit code
        return $LASTEXITCODE
    } finally { Pop-Location }
}

function Test-Health {
    $port = [int](Get-Setting "BI_PORT" "8000")
    $https = [bool](Get-Setting "BI_TLS_CERT")
    $scheme = if ($https) { "https" } else { "http" }
    $url = "${scheme}://127.0.0.1:$port/api/health"
    # The certificate is issued for the server's names, not 127.0.0.1: only the answer is checked here.
    $prev = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    try {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -SkipCertificateCheck
        } else {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        }
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $prev
    }
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { Say "Background server: not installed (run install_service.bat as Administrator)." Yellow; return }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Say ("Task state: {0} · last start {1} · last result {2}" -f $task.State, $info.LastRunTime, $info.LastTaskResult)
    Say ("Runs as: {0}" -f $task.Principal.UserId)
    $addr = (Invoke-PythonQuiet @("-m", "app.serve", "--url"))
    if (Test-Health) { Say "Server answers: $addr" Green } else { Say "Server does not answer on its port. See data\logs\server.log." Red }
}

function Invoke-PythonQuiet([string[]]$PyArgs) {
    Push-Location $Backend
    try { $env:BI_MODE = "production"; return (& $Python @PyArgs 2>$null | Select-Object -Last 1) } finally { Pop-Location }
}

function Remove-Rules {
    Get-NetFirewallRule -DisplayName "$RulePrefix*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}

function Protect-TlsFolder([string]$Who) {
    $tlsDir = Get-Setting "BI_TLS_DIR" (Join-Path $Root "data\tls")
    if (-not (Test-Path $tlsDir)) { return }
    # inheritance off; full control for Administrators and SYSTEM; read for the service account
    & icacls $tlsDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
    if ($Who -and $Who -ne "SYSTEM") { & icacls $tlsDir /grant "${Who}:(OI)(CI)R" | Out-Null }
    Say "Certificate folder restricted: $tlsDir"
}

switch ($Action) {
    "status" { Show-Status; exit 0 }

    "uninstall" {
        if (-not (Test-Admin)) { Fail "Run as Administrator." }
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Say "Background server removed." Green
        } else { Say "Background server was not installed." }
        Remove-Rules
        Say "Firewall rules removed. Data, backups and certificates are kept."
        exit 0
    }

    "restart" {
        if (-not (Test-Admin)) { Fail "Run as Administrator." }
        if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) { Fail "Not installed." }
        if ((Invoke-Python @("-m", "app.serve", "--check")) -ne 0) { Fail "Settings refused — the running server was left as it is." }
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 8
        Show-Status
        exit 0
    }

    "install" {
        if (-not (Test-Admin)) { Fail "Run as Administrator." }
        if (-not (Test-Path $Python)) { Fail "Run setup.bat first (.venv missing)." }
        if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) { Fail "Frontend build missing (frontend\dist)." }
        if (-not (Test-Path $EnvFile)) {
            Copy-Item (Join-Path $Root "server.env.example") $EnvFile
            Fail "server.env was created from the example. Edit it (address, port, certificate), then run install_service.bat again."
        }
        Say "Checking settings…"
        if ((Invoke-Python @("-m", "app.serve", "--check")) -ne 0) { Fail "Fix server.env, then run install_service.bat again." }
        $hostSetting = Get-Setting "BI_HOST" "127.0.0.1"
        if ($hostSetting -ne "127.0.0.1" -and -not (Get-Setting "BI_TLS_CERT") -and -not (Get-Setting "BI_TRUSTED_PROXIES")) {
            Say "WARNING: the server will be reachable from the network WITHOUT HTTPS (passwords travel unencrypted)." Yellow
            $answer = Read-Host "Type YES to continue anyway"
            if ($answer -ne "YES") { Fail "Cancelled. Configure HTTPS (make_certificate.bat) first." }
        }
        Say "Database schema…"
        if ((Invoke-Python @("-m", "app.manage", "db-upgrade")) -ne 0) { Fail "Database upgrade failed." }

        # Task: python -m app.serve in backend\, at start-up, plus a check every 5 minutes that starts it again if it stopped
        $exec = New-ScheduledTaskAction -Execute $Python -Argument "-m app.serve" -WorkingDirectory $Backend
        $boot = New-ScheduledTaskTrigger -AtStartup
        $watch = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
            -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd
        if ($Account) {
            $cred = Get-Credential -UserName $Account -Message "Password of the service account $Account (needs 'Log on as a batch job')"
            $task = New-ScheduledTask -Action $exec -Trigger @($boot, $watch) -Settings $settings -Description "Blasting Intelligence server ($Root)"
            Register-ScheduledTask -TaskName $TaskName -InputObject $task -User $cred.UserName `
                -Password $cred.GetNetworkCredential().Password -Force | Out-Null
            $who = $Account
        } else {
            $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
            Register-ScheduledTask -TaskName $TaskName -Action $exec -Trigger @($boot, $watch) -Settings $settings `
                -Principal $principal -Description "Blasting Intelligence server ($Root)" -Force | Out-Null
            $who = "SYSTEM"
        }
        Say "Scheduled task registered (runs as $who)." Green

        Protect-TlsFolder $who

        if ($hostSetting -ne "127.0.0.1") {
            Remove-Rules
            $ports = @([int](Get-Setting "BI_PORT" "8000"))
            $redir = [int](Get-Setting "BI_HTTP_REDIRECT_PORT" "0")
            if ($redir -gt 0) { $ports += $redir }
            foreach ($p in $ports) {
                New-NetFirewallRule -DisplayName "$RulePrefix (TCP $p)" -Direction Inbound -Protocol TCP -LocalPort $p `
                    -Action Allow -Profile Domain, Private | Out-Null
            }
            Say ("Firewall opened for TCP {0} (Domain and Private networks only)." -f ($ports -join ", ")) Green
        }

        Start-ScheduledTask -TaskName $TaskName
        Say "Starting…"
        $ok = $false
        foreach ($i in 1..20) { Start-Sleep -Seconds 2; if (Test-Health) { $ok = $true; break } }
        if ($ok) {
            Say ("Server running: {0}" -f (Invoke-PythonQuiet @("-m", "app.serve", "--url"))) Green
            Say "It starts automatically with Windows. Logs: data\logs\server.log"
        } else {
            Say "The server did not answer yet. Check data\logs\server.log, then service_status.bat." Yellow
        }
        exit 0
    }
}
