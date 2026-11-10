<#
Relay DAX checker: runs Power BI's own engine (Analysis Services, from Power BI Desktop on this PC) for the
Relay app, so every measure and visual query is checked by the real engine before a report is shared.

The app (in Docker) drops requests in <projects>\.daxcheck\requests. For each one this script starts a private,
hidden engine (local connections only; it stops when this script stops), loads the check model, refreshes it,
collects every object error, runs the request's EVALUATE queries and writes results\<id>.json.

Start: double-click daxcheck\start-daxcheck.cmd, or
       powershell -NoProfile -ExecutionPolicy Bypass -File daxcheck\daxcheck.ps1
#>
param(
    [string]$Queue = (Join-Path $PSScriptRoot "..\output\projects\.daxcheck"),
    [string]$PbiBin = ""
)
$ErrorActionPreference = "Stop"

function Find-PbiBin {
    if ($PbiBin -and (Test-Path (Join-Path $PbiBin "msmdsrv.exe"))) { return $PbiBin }
    foreach ($dir in @("$env:ProgramFiles\Microsoft Power BI Desktop\bin", "${env:ProgramFiles(x86)}\Microsoft Power BI Desktop\bin")) {
        if (Test-Path (Join-Path $dir "msmdsrv.exe")) { return $dir }
    }
    throw "Power BI Desktop was not found. Install it, or pass -PbiBin <folder with msmdsrv.exe>."
}

$Bin = Find-PbiBin
$Queue = [IO.Path]::GetFullPath($Queue)
$Requests = Join-Path $Queue "requests"
$Results = Join-Path $Queue "results"
New-Item -ItemType Directory -Force $Requests, $Results | Out-Null
Add-Type -Path (Join-Path $Bin "Microsoft.PowerBI.Tabular.dll")
Add-Type -Path (Join-Path $Bin "Microsoft.PowerBI.AdomdClient.dll")
$Version = (Get-Item (Join-Path $Bin "PBIDesktop.exe")).VersionInfo.ProductVersion.Split(" ")[0]
$Database = "GenBICheck"

# The engine settings Power BI Desktop itself uses (embedded mode), without its Power Query pipe.
$IniTemplate = @"
<ConfigurationSettings>
  <DataDir>{DATA}</DataDir>
  <TempDir>{DATA}</TempDir>
  <LogDir>{DATA}</LogDir>
  <BackupDir>{DATA}</BackupDir>
  <DeploymentMode>1</DeploymentMode>
  <RecoveryModel>1</RecoveryModel>
  <DisklessModeRequested>1</DisklessModeRequested>
  <CleanDataFolderOnStartup>1</CleanDataFolderOnStartup>
  <AutoSetDefaultInitialCatalog>1</AutoSetDefaultInitialCatalog>
  <Network><ListenOnlyOnLocalConnections>1</ListenOnlyOnLocalConnections></Network>
  <Port>0</Port>
  <PrivateProcess>{PID}</PrivateProcess>
  <InstanceVisible>0</InstanceVisible>
  <Language>1033</Language>
  <Memory><MemoryHeapType>5</MemoryHeapType></Memory>
  <AllowedBrowsingFolders>{DATA}</AllowedBrowsingFolders>
  <ResourceGovernance><GovernIMBIScheduler>0</GovernIMBIScheduler></ResourceGovernance>
  <Feature>
    <ManagedCodeEnabled>1</ManagedCodeEnabled>
    <MetadataAccessPolicyEnabled>1</MetadataAccessPolicyEnabled>
    <EnableDaxEvaluateAndLog>1</EnableDaxEvaluateAndLog>
    <DataSourceReferenceEnabled>2</DataSourceReferenceEnabled>
    <EnableMDQV3>1</EnableMDQV3>
    <VisualCalculations>1</VisualCalculations>
    <PBIP><CombinePartitionMetadataAndData>1</CombinePartitionMetadataAndData></PBIP>
    <DefaultExpressions>3</DefaultExpressions>
    <UnicodeCharacterBehaviorEnabled>1</UnicodeCharacterBehaviorEnabled>
  </Feature>
  <VertiPaq>
    <EnableDisklessTMImageSave>1</EnableDisklessTMImageSave>
    <EnableProcessingSimplifiedLocks>1</EnableProcessingSimplifiedLocks>
  </VertiPaq>
  <DAX>
    <EnableVariationNotation>1</EnableVariationNotation>
    <VirtualColumnOnVirtualTable>1</VirtualColumnOnVirtualTable>
    <UnrestrictedSummarizeColumns>1</UnrestrictedSummarizeColumns>
    <SummarizeColumnsSelfValue>1</SummarizeColumnsSelfValue>
    <EnableSeparateDaxParser>1</EnableSeparateDaxParser>
  </DAX>
</ConfigurationSettings>
"@

$script:LastBeat = [DateTime]::MinValue
function Write-Heartbeat([string]$state) {
    if ($state -eq "idle" -and ((Get-Date) - $script:LastBeat).TotalSeconds -lt 5) { return }
    $beat = [ordered]@{ time = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); pid = $PID; engine = $Version; state = $state }
    $tmp = Join-Path $Queue "heartbeat.json.tmp"
    [IO.File]::WriteAllText($tmp, ($beat | ConvertTo-Json -Compress))
    Move-Item -Force $tmp (Join-Path $Queue "heartbeat.json")
    $script:LastBeat = Get-Date
}

function Start-Engine {
    $ws = Join-Path $env:TEMP ("genbi-daxcheck-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $data = Join-Path $ws "Data"
    New-Item -ItemType Directory -Force $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data "msmdsrv.ini"), $IniTemplate.Replace("{DATA}", $data).Replace("{PID}", "$PID"))
    $p = Start-Process -FilePath (Join-Path $Bin "msmdsrv.exe") -ArgumentList "-c -n GenBIDaxCheck -s `"$data`"" -WindowStyle Hidden -PassThru
    $portFile = Join-Path $data "msmdsrv.port.txt"
    $t0 = Get-Date
    while (-not (Test-Path $portFile) -and -not $p.HasExited -and ((Get-Date) - $t0).TotalSeconds -lt 60) { Start-Sleep -Milliseconds 200 }
    if (-not (Test-Path $portFile)) { throw "the engine did not start" }
    Start-Sleep -Milliseconds 200
    $port = ([IO.File]::ReadAllText($portFile, [Text.Encoding]::Unicode)).Trim()
    return @{ Process = $p; Port = $port; Dir = $ws }
}

function Stop-Engine($engine) {
    if (-not $engine) { return }
    try { Stop-Process -Id $engine.Process.Id -Force -ErrorAction SilentlyContinue } catch {}
    for ($i = 0; $i -lt 10; $i++) {
        try { Remove-Item $engine.Dir -Recurse -Force -ErrorAction Stop; break } catch { Start-Sleep -Milliseconds 300 }
    }
}

function Get-Messages($results) {
    $list = New-Object System.Collections.ArrayList
    foreach ($r in $results) { foreach ($m in $r.Messages) { [void]$list.Add([string]$m.Description) } }
    return ,$list
}

function Get-States($model) {
    $list = New-Object System.Collections.ArrayList
    foreach ($t in $model.Tables) {
        foreach ($p in $t.Partitions) {
            if ($p.ErrorMessage) { [void]$list.Add([ordered]@{ kind = "table"; name = $t.Name; state = "$($p.State)"; error = $p.ErrorMessage }) }
        }
        foreach ($c in $t.Columns) {
            if ($c.ErrorMessage) { [void]$list.Add([ordered]@{ kind = "column"; name = "$($t.Name)[$($c.Name)]"; state = "$($c.State)"; error = $c.ErrorMessage }) }
        }
        foreach ($m in $t.Measures) {
            if ($m.ErrorMessage) { [void]$list.Add([ordered]@{ kind = "measure"; name = "[$($m.Name)]"; state = "$($m.State)"; error = $m.ErrorMessage }) }
        }
    }
    return ,$list
}

function Convert-Value($v) {
    if ($v -is [DBNull] -or $null -eq $v) { return $null }
    if ($v -is [DateTime]) { return $v.ToString("yyyy-MM-dd HH:mm:ss") }
    if ($v -is [bool] -or $v -is [string]) { return $v }
    if ($v -is [ValueType]) { return [double]$v }
    return [string]$v
}

function Invoke-Query($conn, $q) {
    $r = [ordered]@{ key = [string]$q.key; ok = $false; columns = (New-Object System.Collections.ArrayList); rows = (New-Object System.Collections.ArrayList); count = 0; error = $null }
    if (-not ([string]$q.dax -match '^\s*EVALUATE\b')) { $r.error = "only EVALUATE queries are run"; return $r }
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = [string]$q.dax
        $cmd.CommandTimeout = 60
        $rd = $cmd.ExecuteReader()
        try {
            for ($i = 0; $i -lt $rd.FieldCount; $i++) { [void]$r.columns.Add($rd.GetName($i)) }
            while ($rd.Read()) {
                $r.count++
                if ($r.rows.Count -lt 20) {
                    $row = New-Object System.Collections.ArrayList
                    for ($i = 0; $i -lt $rd.FieldCount; $i++) { [void]$row.Add((Convert-Value $rd.GetValue($i))) }
                    [void]$r.rows.Add($row)
                }
            }
        } finally { $rd.Close() }
        $r.ok = $true
    } catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        $r.error = $e.Message
    }
    return $r
}

function Invoke-Check($file) {
    $id = $file.BaseName
    $modelPath = Join-Path $Requests "$id.model.json"
    $out = [ordered]@{ id = $id; ok = $false; engine = $Version; seconds = 0; error = $null
                       messages = (New-Object System.Collections.ArrayList); objects = (New-Object System.Collections.ArrayList)
                       queries = (New-Object System.Collections.ArrayList) }
    $t0 = Get-Date
    $engine = $null; $srv = $null; $conn = $null
    Write-Heartbeat "checking"
    try {
        $req = [IO.File]::ReadAllText($file.FullName) | ConvertFrom-Json
        $model = [IO.File]::ReadAllText($modelPath).Trim()
        if (-not ($model.StartsWith("{") -and $model.Contains("`"$Database`""))) { throw "the request's model is not a $Database database" }
        Write-Host ("{0:HH:mm:ss} {1}: {2} queries" -f (Get-Date), $req.project, @($req.queries).Count)
        $engine = Start-Engine
        $srv = New-Object Microsoft.AnalysisServices.Tabular.Server
        $srv.Connect("Data Source=localhost:$($engine.Port)")
        $msgs = Get-Messages ($srv.Execute('{"createOrReplace":{"object":{"database":"' + $Database + '"},"database":' + $model + '}}'))
        foreach ($m in $msgs) { [void]$out.messages.Add($m) }
        $msgs = Get-Messages ($srv.Execute('{"refresh":{"type":"full","objects":[{"database":"' + $Database + '"}]}}'))
        foreach ($m in $msgs) { [void]$out.messages.Add($m) }
        $srv.Refresh($true)
        $db = $srv.Databases.GetByName($Database)
        $out.objects = Get-States $db.Model
        $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($engine.Port);Catalog=$Database")
        $conn.Open()
        foreach ($q in @($req.queries)) { [void]$out.queries.Add((Invoke-Query $conn $q)) }
        $out.ok = $true
    } catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        $out.error = $e.Message
    } finally {
        if ($conn) { try { $conn.Close() } catch {} }
        if ($srv) { try { $srv.Disconnect() } catch {} }
        Stop-Engine $engine
    }
    $out.seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $bad = @($out.objects).Count + @($out.queries | Where-Object { -not $_.ok }).Count
    Write-Host ("{0:HH:mm:ss}   done in {1} s, {2} problem(s){3}" -f (Get-Date), $out.seconds, $bad, $(if ($out.error) { ": " + $out.error } else { "" }))
    $tmp = Join-Path $Results "$id.json.tmp"
    [IO.File]::WriteAllText($tmp, ($out | ConvertTo-Json -Depth 8))
    Move-Item -Force $tmp (Join-Path $Results "$id.json")
    Remove-Item -Force $file.FullName, $modelPath -ErrorAction SilentlyContinue
}

Write-Host "Relay DAX checker: Power BI Desktop $Version engine, queue $Queue"
Write-Host "Leave this window open while you use the app (minimise it). Ctrl+C stops it."
while ($true) {
    Write-Heartbeat "idle"
    $next = Get-ChildItem $Requests -Filter "*.json" | Where-Object { $_.Name -notlike "*.model.json" } | Sort-Object LastWriteTime | Select-Object -First 1
    if ($next) {
        try { Invoke-Check $next } catch { Write-Host "error: $($_.Exception.Message)"; Remove-Item -Force $next.FullName -ErrorAction SilentlyContinue }
    } else {
        Start-Sleep -Milliseconds 500
    }
    # results nobody collected (the app gave up waiting) are removed after an hour
    Get-ChildItem $Results -Filter "*.json" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) } | Remove-Item -Force -ErrorAction SilentlyContinue
}
