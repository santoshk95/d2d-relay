<#
The PC helpers for the TEST stack only, never live's: the DAX checker and the Power BI file maker from this
repository, each on the test stack's own queue (tests\stack\test-projects\.daxcheck and .pbix); the file maker with a
data folder of its own (default C:\D2D Relay Test). Live's helpers (from Downloads\D2D Relay, on live's queues and
C:\D2D Relay Data) are not touched: each helper runs one copy per queue or data folder, and Power BI Desktop's Save as
is taken in turn with live's maker (the shared Local\PbixBot-Convert lock).
  powershell -NoProfile -ExecutionPolicy Bypass -File tests\stack\helpers.ps1 start|status|stop
Start them after stack.sh (it makes test-projects); stop them before taking the stack down. They are started through
WMI so they keep running after the command that started them ends, in the signed-in Windows session (the file maker
drives Power BI Desktop there).
#>
param([Parameter(Mandatory)][ValidateSet('start', 'status', 'stop')][string]$Action,
      [string]$DataRoot = 'C:\D2D Relay Test')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$projects = Join-Path $PSScriptRoot 'test-projects'
$pidFile = Join-Path $PSScriptRoot 'helpers.pids'
$helpers = @(
    @{Name = 'DAX checker'; Queue = (Join-Path $projects '.daxcheck'); Script = (Join-Path $repo 'daxcheck\daxcheck.ps1'); Extra = ''},
    @{Name = 'Power BI file maker'; Queue = (Join-Path $projects '.pbix'); Script = (Join-Path $repo 'pbix\pbix.ps1'); Extra = " -DataRoot `"$DataRoot`""}
)

function Beat([string]$queue) {
    $f = Join-Path $queue 'heartbeat.json'
    if (-not (Test-Path -LiteralPath $f)) { return 'no heartbeat yet' }
    try {
        $b = Get-Content -Raw -LiteralPath $f | ConvertFrom-Json
        $age = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$b.time)
        return "$($b.state), heartbeat ${age}s ago"
    } catch { return 'heartbeat unreadable' }
}

switch ($Action) {
    'start' {
        if (-not (Test-Path -LiteralPath $projects)) { throw "Start the test stack first (stack.sh): $projects is missing." }
        if ($DataRoot.TrimEnd('\') -ieq 'C:\D2D Relay Data') { throw "That is live's data folder; the test file maker needs its own." }
        $ids = @()
        foreach ($h in $helpers) {
            New-Item -ItemType Directory -Force -Path $h.Queue | Out-Null
            $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$($h.Script)`" -Queue `"$($h.Queue)`"$($h.Extra)"
            $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
            if ($r.ReturnValue -ne 0) { throw "$($h.Name) did not start (Win32_Process.Create returned $($r.ReturnValue))" }
            $ids += $r.ProcessId
            "$($h.Name): started, process $($r.ProcessId), queue $($h.Queue)"
        }
        Set-Content -LiteralPath $pidFile -Value ($ids -join ' ') -Encoding ascii
        Start-Sleep -Seconds 20
        foreach ($h in $helpers) { "$($h.Name): $(Beat $h.Queue)" }
    }
    'status' { foreach ($h in $helpers) { "$($h.Name): $(Beat $h.Queue)" } }
    'stop' {
        if (Test-Path -LiteralPath $pidFile) {
            foreach ($id in (Get-Content -LiteralPath $pidFile).Split(' ', [StringSplitOptions]::RemoveEmptyEntries)) {
                $p = Get-CimInstance Win32_Process -Filter "ProcessId = $id"
                # only a helper started for this test stack: its command line names the test queue
                if ($p -and $p.CommandLine -like '*\tests\stack\test-projects\*') { Stop-Process -Id $id -Force; "stopped process $id" }
            }
            Remove-Item -LiteralPath $pidFile
        }
        if ((Test-Path -LiteralPath (Join-Path $DataRoot '.d2d-relay-converter')) -and $DataRoot.TrimEnd('\') -ine 'C:\D2D Relay Data') {
            Remove-Item -LiteralPath $DataRoot -Recurse -Force
            "removed $DataRoot"
        }
    }
}
