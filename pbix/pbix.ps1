<#
D2D Relay's Power BI file maker: Power BI Desktop on this PC turns every published dashboard into a .pbix file.

The app (in Docker) drops requests in <projects>\.pbix\requests. For each one this script runs Convert-D2DZip.ps1:
it opens the checked report in Power BI Desktop, refreshes it from the dashboard's CSVs, checks with Power BI's own
engine that every table loaded, saves it as a .pbix, and writes results\<id>.json. One at a time.

The data is refreshed from <DataRoot>\<Report>\data (default C:\D2D Relay Data), so every .pbix carries that same
DataFolder path, whichever PC made it: unzip the download into C:\D2D Relay Data and a refresh in Power BI Desktop
finds its CSVs. This script owns <DataRoot> (marked by a .d2d-relay-converter file) and empties each report's folder
after use; it refuses a folder of that name that it did not make. Power BI Desktop works in <DataRoot>\.work, a short
path: Save as fails once a report's files lie deeper than Windows' 260 characters.

Needs Power BI Desktop (from the Microsoft Download Center, English) and a signed-in Windows session: it drives
Power BI Desktop's window, so windows open and close by themselves while it works.

Start: double-click pbix\start-pbix.cmd, or
       powershell -NoProfile -ExecutionPolicy Bypass -File pbix\pbix.ps1
#>
param(
    [string]$Queue = (Join-Path $PSScriptRoot "..\data\projects\.pbix"),
    [string]$DataRoot = "C:\D2D Relay Data",
    [string]$PbiDesktopPath = "",
    [int]$TimeoutMinutes = 75
)
$ErrorActionPreference = "Stop"

$Queue = [IO.Path]::GetFullPath($Queue)
$Projects = Split-Path -Parent $Queue
$Requests = Join-Path $Queue "requests"
$Results = Join-Path $Queue "results"
$Work = Join-Path $Queue "work"
New-Item -ItemType Directory -Force $Requests, $Results, $Work | Out-Null
$Converter = Join-Path $PSScriptRoot "Convert-D2DZip.ps1"
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$Marker = Join-Path $DataRoot ".d2d-relay-converter"
$Utf8 = New-Object Text.UTF8Encoding($false)

# One maker per data folder: a second one would empty the first one's work folder (and share its queue)
$key = [BitConverter]::ToString([Security.Cryptography.SHA1]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($DataRoot.ToLowerInvariant()))).Replace('-', '').Substring(0, 16)
$Single = New-Object Threading.Mutex($false, "Local\D2DRelay-PbixMaker-$key")
$mine = $false
try { $mine = $Single.WaitOne(0) } catch [Threading.AbandonedMutexException] { $mine = $true }
if (-not $mine) {
    Write-Host "The D2D Relay Power BI file maker is already running for $DataRoot (another window). This one closes."
    Start-Sleep -Seconds 8
    exit 1
}

# <DataRoot> is this script's own: make it (with its marker), or use it only if it carries the marker
$Fatal = $null
try {
    if (-not (Test-Path -LiteralPath $Converter)) { throw "Convert-D2DZip.ps1 is missing next to this script." }
    if (-not (Test-Path -LiteralPath $DataRoot)) { New-Item -ItemType Directory -Force $DataRoot | Out-Null }
    if (-not (Test-Path -LiteralPath $Marker)) {
        if (@(Get-ChildItem -LiteralPath $DataRoot -Force).Count -gt 0) {
            throw "$DataRoot already holds files that are not the Power BI file maker's. Empty it, or start with -DataRoot <another folder>."
        }
        [IO.File]::WriteAllText($Marker, "D2D Relay's Power BI file maker works here (pbix\pbix.ps1). Each report's folder is emptied after use.", $Utf8)
    }
} catch { $Fatal = $_.Exception.Message }

$script:LastBeat = [DateTime]::MinValue
function Write-Heartbeat([string]$state, [string]$current = $null, [string]$problem = $null) {
    if ($state -eq "idle" -and ((Get-Date) - $script:LastBeat).TotalSeconds -lt 5) { return }
    $beat = [ordered]@{ time = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); pid = $PID; state = $state; current = $current; data_root = $DataRoot;
                        error = $problem }
    $tmp = Join-Path $Queue "heartbeat.json.tmp"
    [IO.File]::WriteAllText($tmp, ($beat | ConvertTo-Json -Compress), $Utf8)
    Move-Item -Force $tmp (Join-Path $Queue "heartbeat.json")
    $script:LastBeat = Get-Date
}

function Write-Answer([string]$id, $answer) {
    $tmp = Join-Path $Results "$id.json.tmp"
    [IO.File]::WriteAllText($tmp, ($answer | ConvertTo-Json -Depth 4), $Utf8)
    Move-Item -Force $tmp (Join-Path $Results "$id.json")
}

# A path the request names, relative to the projects folder: it must stay inside it
function Resolve-Inside([string]$rel) {
    $full = [IO.Path]::GetFullPath((Join-Path $Projects ($rel -replace '/', '\')))
    if (-not $full.StartsWith($Projects.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Not inside the projects folder: $rel" }
    return $full
}

function Quote([string]$s) { return '"' + $s + '"' }

# ---------------------------------------------------------------- what a report may do on this PC
# Reports are refreshed here, on the PC that runs D2D Relay, so their Power Query may only read their own data files:
# File.Contents(DataFolder & "<a file of the dashboard's data folder>") and the functions D2D Relay's report builder
# writes. Anything else (another folder, the web, a database, #shared, a DataFolder of its own) is refused before
# Power BI Desktop opens the report. A warehouse report is not refreshed here at all (its owner refreshes it with
# their own sign-in), so only then are the warehouse connectors allowed.
$SafeFunctions = @('Csv.Document', 'File.Contents', 'Parquet.Document', 'QuoteStyle.Csv', 'QuoteStyle.None',
    'Table.PromoteHeaders', 'Table.TransformColumnTypes', 'Table.RenameColumns', 'Table.SelectColumns', 'Table.ReplaceValue',
    'Replacer.ReplaceValue', 'Replacer.ReplaceText', 'Table.DuplicateColumn', 'Table.AddColumn', 'Table.FromList',
    'Splitter.SplitByNothing', 'List.Dates', 'Duration.Days', 'Date.Day', 'Date.DayOfWeek', 'Date.Month', 'Date.QuarterOfYear',
    'Date.StartOfMonth', 'Date.ToText', 'Date.Year', 'Day.Monday', 'Text.From', 'Int64.Type', 'Currency.Type', 'Percentage.Type')
$WarehouseFunctions = @('Snowflake.Databases', 'GoogleBigQuery.Database', 'Sql.Database', 'AmazonRedshift.Database',
    'AmazonAthena.Databases', 'Oracle.Database')
$SafeIntrinsics = @('#date', '#duration', '#datetime', '#time')
$PlainFile = '^[^\\/:*?"<>|.][^\\/:*?"<>|]*$'

# Power Query text as tokens @(kind, value): str (a text), qid (#"a name"), hash (#date ...), id (a name; with dots, a
# library function) or p (any other character). Comments are dropped, as Power Query drops them.
function Get-MTokens([string]$m) {
    $t = New-Object 'System.Collections.Generic.List[string[]]'
    $i = 0; $n = $m.Length
    while ($i -lt $n) {
        $c = $m[$i]
        if ([char]::IsWhiteSpace($c)) { $i++; continue }
        if ($c -eq '/' -and $i + 1 -lt $n -and $m[$i + 1] -eq '/') { $j = $m.IndexOf([char]10, $i); if ($j -lt 0) { $j = $n }; $i = $j; continue }
        if ($c -eq '/' -and $i + 1 -lt $n -and $m[$i + 1] -eq '*') {
            $j = $m.IndexOf('*/', $i + 2, [StringComparison]::Ordinal); if ($j -lt 0) { throw 'a comment does not end' }; $i = $j + 2; continue
        }
        if ($c -eq '"' -or ($c -eq '#' -and $i + 1 -lt $n -and $m[$i + 1] -eq '"')) {
            $kind = 'str'; if ($c -eq '#') { $kind = 'qid'; $i++ }
            $i++; $sb = New-Object Text.StringBuilder
            while ($true) {
                if ($i -ge $n) { throw 'a text does not end' }
                if ($m[$i] -eq '"') { if ($i + 1 -lt $n -and $m[$i + 1] -eq '"') { [void]$sb.Append('"'); $i += 2; continue }; $i++; break }
                [void]$sb.Append($m[$i]); $i++
            }
            $t.Add([string[]]@($kind, $sb.ToString())); continue
        }
        if ($c -eq '#' -or $c -eq '_' -or [char]::IsLetter($c)) {
            $j = $i + 1
            while ($j -lt $n -and ($m[$j] -eq '_' -or $m[$j] -eq '.' -or [char]::IsLetterOrDigit($m[$j]))) { $j++ }
            $word = $m.Substring($i, $j - $i).TrimEnd('.')
            $kind = 'id'; if ($c -eq '#') { $kind = 'hash' }
            $t.Add([string[]]@($kind, $word)); $i += $word.Length; continue
        }
        $t.Add([string[]]@('p', [string]$c)); $i++
    }
    return , $t
}

# Why this report may not be opened here (refreshed, or only saved when -not $Refresh), or $null when it may
function Test-ReportQueries([string]$ZipFile, [string]$DataDir, [bool]$Refresh) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipFile)
    try {
        $names = @($zip.Entries | ForEach-Object { $_.FullName })
        $pbips = @($names | Where-Object { $_ -like '*.pbip' })
        $bims = @($names | Where-Object { $_ -like '*.SemanticModel/model.bim' })
        if ($pbips.Count -ne 1 -or $bims.Count -ne 1) { return "it should hold one report and one model, it holds $($pbips.Count) and $($bims.Count)" }
        if (@($names | Where-Object { $_ -like '*.tmdl' -or $_ -like '*.pbix' }).Count -gt 0) { return 'it holds files D2D Relay does not write' }
        $reader = New-Object IO.StreamReader($zip.GetEntry($bims[0]).Open(), (New-Object Text.UTF8Encoding($false)))
        try { $json = $reader.ReadToEnd() } finally { $reader.Close() }
    }
    finally { $zip.Dispose() }
    $model = ($json | ConvertFrom-Json).model
    if ($model.dataSources -and @($model.dataSources).Count -gt 0) { return 'its model has data sources of its own' }
    $allowed = $SafeFunctions; if (-not $Refresh) { $allowed = $SafeFunctions + $WarehouseFunctions }
    $queries = New-Object 'System.Collections.Generic.List[string[]]'
    foreach ($tb in @($model.tables)) {
        if (-not $tb) { continue }
        foreach ($pt in @($tb.partitions)) {
            if (-not $pt) { continue }
            if ($pt.source.type -eq 'calculated') { continue }
            if ($pt.source.type -ne 'm') { return "table $($tb.name) reads its data in a way D2D Relay does not write" }
            $queries.Add([string[]]@("table $($tb.name)", (@($pt.source.expression) -join "`n")))
        }
    }
    foreach ($x in @($model.expressions)) { if ($x) { $queries.Add([string[]]@("query $($x.name)", (@($x.expression) -join "`n"))) } }
    foreach ($q in $queries) {
        $where = $q[0]
        try { $tok = Get-MTokens $q[1] } catch { return "$where cannot be read ($($_.Exception.Message))" }
        for ($k = 0; $k -lt $tok.Count; $k++) {
            $kind = $tok[$k][0]; $v = $tok[$k][1]
            if ($kind -eq 'hash' -and $SafeIntrinsics -notcontains $v) { return "$where uses $v" }
            if ($kind -eq 'qid' -and ($v -eq 'DataFolder' -or $v.Contains('.'))) { return "$where uses the name `"$v`"" }
            if ($kind -ne 'id') { continue }
            if ($v -eq 'DataFolder') {        # only in File.Contents(DataFolder & "<file>")
                $ok = $k -ge 2 -and $k + 3 -lt $tok.Count -and $tok[$k - 2][0] -eq 'id' -and $tok[$k - 2][1] -eq 'File.Contents' -and
                    $tok[$k - 1][0] -eq 'p' -and $tok[$k - 1][1] -eq '(' -and $tok[$k + 1][0] -eq 'p' -and $tok[$k + 1][1] -eq '&' -and
                    $tok[$k + 2][0] -eq 'str' -and $tok[$k + 3][0] -eq 'p' -and $tok[$k + 3][1] -eq ')'
                if (-not $ok) { return "$where uses DataFolder other than to read one of its own files" }
                $file = $tok[$k + 2][1]
                if ($file -notmatch $PlainFile -or -not (Test-Path -LiteralPath (Join-Path $DataDir $file) -PathType Leaf)) {
                    return "$where reads '$file', which is not one of the dashboard's data files"
                }
                continue
            }
            if (-not $v.Contains('.')) { continue }
            if ($allowed -notcontains $v) { return "$where uses $v" }
            if ($v -eq 'File.Contents' -and -not ($k + 2 -lt $tok.Count -and $tok[$k + 1][1] -eq '(' -and $tok[$k + 2][0] -eq 'id' -and $tok[$k + 2][1] -eq 'DataFolder')) {
                return "$where reads a file that is not one of the dashboard's data files"
            }
        }
    }
    return $null
}

# Power BI Desktop works in a short folder: a report's own files sit about 100 characters deep (pages, visuals), and
# Save as fails ("Object reference not set to an instance of an object") once a path passes Windows' 260 characters.
$Short = Join-Path $DataRoot ".work"

function Clear-Short {
    if (Test-Path -LiteralPath $Short) { Remove-Item -LiteralPath $Short -Recurse -Force -ErrorAction SilentlyContinue }
}

function Invoke-Request([IO.FileInfo]$file) {
    $req = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $id = [string]$req.id
    $report = [string]$req.report
    $root = Join-Path $Work $id          # kept a day when it fails: the converter's log and its picture of the window
    $started = Get-Date
    $ok = $false
    try {
        if ($report -notmatch '^[^\\/:*?"<>|.][^\\/:*?"<>|]*$') { throw "Not a report name: $report" }
        $zip = Resolve-Inside $req.zip
        $data = Resolve-Inside $req.data
        $out = Resolve-Inside $req.out
        if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw "The checked report is missing: $($req.zip)" }
        $refresh = -not ($req.PSObject.Properties['refresh'] -and $req.refresh -eq $false)      # false: a warehouse report
        $refused = Test-ReportQueries $zip $data $refresh
        if ($refused) { throw "This report was not opened on the D2D Relay PC: $refused." }
        Write-Host ("{0:HH:mm:ss}  {1}: making {2}.pbix{3}" -f (Get-Date), $id, $report, $(if ($refresh) { '' } else { ' (not refreshed)' }))
        Clear-Short
        $inbox = Join-Path $Short "Inbox"
        New-Item -ItemType Directory -Force $inbox | Out-Null
        $inZip = Join-Path $inbox "$report.zip"
        Copy-Item -LiteralPath $zip -Destination $inZip
        $resultFile = Join-Path $Short "result.txt"
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File " + (Quote $Converter) + " -ZipPath " + (Quote $inZip) + " -RootFolder " + (Quote $Short) +
            " -ResultFile " + (Quote $resultFile) + " -DataRoot " + (Quote $DataRoot)
        if (Test-Path -LiteralPath $data -PathType Container) { $arguments += " -DataSource " + (Quote $data) }
        if ($PbiDesktopPath) { $arguments += " -PbiDesktopPath " + (Quote $PbiDesktopPath) }
        if (-not $refresh) { $arguments += " -NoRefresh" }
        $p = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -PassThru -WindowStyle Minimized
        $deadline = $started.AddMinutes($TimeoutMinutes)
        while (-not $p.HasExited) {
            Write-Heartbeat "making" $id
            if ((Get-Date) -gt $deadline) {
                & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null
                throw "Power BI Desktop took longer than $TimeoutMinutes minutes."
            }
            Start-Sleep -Seconds 2
        }
        $lines = @()
        if (Test-Path -LiteralPath $resultFile) { $lines = @(Get-Content -LiteralPath $resultFile -Encoding UTF8) }
        if ($lines.Count -ge 2 -and $lines[0] -eq "OK") {
            $pbix = $lines[1].Trim()
            New-Item -ItemType Directory -Force (Split-Path -Parent $out) | Out-Null
            Copy-Item -LiteralPath $pbix -Destination $out -Force
            $mb = [math]::Round((Get-Item -LiteralPath $out).Length / 1MB, 1)
            Write-Answer $id ([ordered]@{ id = $id; ok = $true; pbix = $req.out; data_folder = (Join-Path (Join-Path $DataRoot $report) "data") + "\";
                                          seconds = [int]((Get-Date) - $started).TotalSeconds; mb = $mb; refreshed = $refresh })
            Write-Host ("{0:HH:mm:ss}  {1}: done, {2} MB in {3:n0} s" -f (Get-Date), $id, $mb, ((Get-Date) - $started).TotalSeconds)
            $ok = $true
        }
        else {
            $reason = "Power BI Desktop could not make the .pbix."
            if ($lines.Count -ge 2) { $reason = $lines[1].Trim() }
            $log = @()
            $logFile = Get-ChildItem -LiteralPath (Join-Path $Short "Logs") -Filter "*.log" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($logFile) { $log = @(Get-Content -LiteralPath $logFile.FullName -Tail 25 -Encoding UTF8) }
            throw [Exception]::new($reason + "`n" + ($log -join "`n"))
        }
    }
    catch {
        $text = $_.Exception.Message
        $first, $rest = $text -split "`n", 2
        Write-Answer $id ([ordered]@{ id = $id; ok = $false; error = $first; log = @(($rest -split "`n") | Where-Object { $_ }); seconds = [int]((Get-Date) - $started).TotalSeconds })
        Write-Host ("{0:HH:mm:ss}  {1}: FAILED: {2}" -f (Get-Date), $id, $first)
        try {                           # keep the converter's log and picture of the window (not the report) for a day
            New-Item -ItemType Directory -Force $root | Out-Null
            Get-ChildItem -LiteralPath $Short -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { @('.log', '.png', '.txt') -contains $_.Extension.ToLowerInvariant() } |
                ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $root -Force }
        } catch { }
    }
    finally {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
        if ($report -and $report -notmatch '[\\/]' -and -not $report.StartsWith('.')) {
            Remove-Item -LiteralPath (Join-Path $DataRoot $report) -Recurse -Force -ErrorAction SilentlyContinue
        }
        Clear-Short
    }
}

if ($Fatal) {                   # the app shows this reason instead of "not running"; fix it, then start again
    Write-Host "D2D Relay Power BI file maker STOPPED: $Fatal"
    while ($true) { Write-Heartbeat "error" $null $Fatal; Start-Sleep -Seconds 5 }
}
Clear-Short                     # left by a run that was stopped half-way
Write-Host "D2D Relay Power BI file maker: queue $Queue, data folder $DataRoot"
Write-Host "Leave this window open while D2D Relay is in use (minimise it). Ctrl+C stops it."
while ($true) {
    Write-Heartbeat "idle"
    $next = Get-ChildItem -LiteralPath $Requests -Filter "*.json" | Sort-Object LastWriteTime | Select-Object -First 1
    if ($next) {
        try { Invoke-Request $next } catch { Write-Host "error: $($_.Exception.Message)"; Remove-Item -Force $next.FullName -ErrorAction SilentlyContinue }
    } else {
        Start-Sleep -Milliseconds 1000
    }
    # answers nobody collected (the app gave up waiting) go after an hour; failed work folders after a day
    Get-ChildItem -LiteralPath $Results -Filter "*.json" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) } | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $Work -Directory | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
