[CmdletBinding()]
param(
    [string]$Nvidia1Host = $env:WAMOCON_NVIDIA1_SSH_HOST,
    [string]$Nvidia2Host = $env:WAMOCON_NVIDIA2_SSH_HOST
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Nvidia1Host) -or [string]::IsNullOrWhiteSpace($Nvidia2Host)) {
    throw "Supply -Nvidia1Host and -Nvidia2Host (or the WAMOCON_NVIDIA1_SSH_HOST and WAMOCON_NVIDIA2_SSH_HOST environment variables)."
}

function Test-LoopbackPort {
    param([Parameter(Mandatory)][int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(700)) {
            return $false
        }
        $client.EndConnect($pending)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Assert-ExpectedEndpoint {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 8 -UseBasicParsing
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) {
            throw "unexpected HTTP status $($response.StatusCode)"
        }
    }
    catch {
        throw "$Name is listening but did not answer its expected local endpoint: $($_.Exception.Message)"
    }
}

$forwards = @(
    [pscustomobject]@{
        Name = "SearxNG"
        LocalPort = 18090
        RemotePort = 8090
        HostAlias = $Nvidia1Host
        ProbeUrl = "http://127.0.0.1:18090/"
    },
    [pscustomobject]@{
        Name = "Qwen / Ollama"
        LocalPort = 18114
        RemotePort = 11434
        HostAlias = $Nvidia2Host
        ProbeUrl = "http://127.0.0.1:18114/api/tags"
    },
    [pscustomobject]@{
        Name = "ComfyUI qualification candidate"
        LocalPort = 18189
        RemotePort = 18189
        HostAlias = $Nvidia2Host
        ProbeUrl = "http://127.0.0.1:18189/system_stats"
    }
)

$results = foreach ($forward in $forwards) {
    $startedProcess = $null
    if (-not (Test-LoopbackPort -Port $forward.LocalPort)) {
        $arguments = @(
            "-N",
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-L", "127.0.0.1:$($forward.LocalPort):127.0.0.1:$($forward.RemotePort)",
            $forward.HostAlias
        )
        $startedProcess = Start-Process -FilePath "ssh.exe" -ArgumentList $arguments -PassThru -WindowStyle Hidden

        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while (-not (Test-LoopbackPort -Port $forward.LocalPort)) {
            if ($startedProcess.HasExited) {
                throw "$($forward.Name) SSH forward exited before opening its loopback port."
            }
            if ([DateTime]::UtcNow -ge $deadline) {
                Stop-Process -Id $startedProcess.Id -ErrorAction SilentlyContinue
                throw "$($forward.Name) SSH forward did not open within 15 seconds."
            }
            Start-Sleep -Milliseconds 250
            $startedProcess.Refresh()
        }
    }

    Assert-ExpectedEndpoint -Name $forward.Name -Url $forward.ProbeUrl
    [pscustomobject]@{
        Dependency = $forward.Name
        Loopback = "127.0.0.1:$($forward.LocalPort)"
        Status = if ($startedProcess) { "started" } else { "already healthy" }
        ProcessId = if ($startedProcess) { $startedProcess.Id } else { $null }
    }
}

$results | Format-Table -AutoSize
