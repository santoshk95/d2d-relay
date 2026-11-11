<#
.SYNOPSIS
    Turns a zip holding a .pbip project (and a data\ folder of CSVs) into a .pbix file with its
    data, using Power BI Desktop. D2D Relay's Power BI file maker (pbix.ps1) runs it for every
    published dashboard; the PbixFromZip UiPath bot runs its own copy for zips dropped in its inbox.

.DESCRIPTION
    For each project in the zip:
      1. Unzips the zip into <Root>\_work\<time stamp>.
      2. Copies the CSVs (from -DataSource, or the zip's data folder) to <Root>\Output\<Report>\data,
         or to <DataRoot>\<Report>\data with -DataRoot, and points the model's DataFolder parameter
         there, so the .pbix refreshes from those CSVs.
      3. Opens the project in Power BI Desktop, refreshes it, checks with Power BI's own data
         engine that every table loaded, and saves it as a .pbix
         (File > Save as > Browse this device > "Power BI file (*.pbix)").
      4. Moves the .pbix to <Root>\Output\<Report>\ and closes Power BI Desktop.
    Then moves the zip to <Root>\Done, or to <Root>\Failed with a log and a picture of the
    Power BI window.

    A zip that already holds a .pbix (and no .pbip) is copied through as it is.

    Microsoft offers no command-line conversion from .pbip to .pbix: Save as in Power BI
    Desktop is the only supported way. So this script drives Desktop's own screens with
    Windows UI Automation and standard window messages; it does not move the mouse or type.

    Needs: Power BI Desktop (English UI) from the Microsoft Download Center, Windows PowerShell 5.1,
    and a signed-in Windows session (Power BI Desktop is a desktop app).

.PARAMETER ZipPath
    The D2D download (.zip).
.PARAMETER RootFolder
    The converter's folder: Output, Done, Failed, Logs and _work live under it.
.PARAMETER ResultFile
    Optional. Gets "OK" or "FAILED" on the first line, then the .pbix path(s) or the reason.
.PARAMETER PbiDesktopPath
    Optional. Full path of PBIDesktop.exe, if it isn't in the default place.
.PARAMETER DataSource
    Optional. The folder the data comes from (default: the data folder in the zip).
.PARAMETER DataRoot
    Optional. Put the data at <DataRoot>\<Report>\data and point DataFolder there: the path every
    .pbix is made with, so it is the same on any PC (D2D Relay: C:\D2D Relay Data). Default: next
    to the .pbix in <Root>\Output\<Report>\data.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Convert-D2DZip.ps1 -ZipPath "C:\Users\me\PbixBot\Inbox\Sales.zip" -RootFolder "C:\Users\me\PbixBot"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ZipPath,
    [Parameter(Mandatory = $true)] [string] $RootFolder,
    [string] $ResultFile,
    [string] $PbiDesktopPath,
    [int] $OpenTimeoutSeconds = 300,
    [int] $RefreshTimeoutSeconds = 3600,
    [int] $SaveTimeoutSeconds = 900,
    [switch] $KeepWorkFolder,
    [string] $DataSource,
    [string] $DataRoot
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ================================================================ folders, log, result

$RootFolder = [IO.Path]::GetFullPath($RootFolder)
$ZipPath = [IO.Path]::GetFullPath($ZipPath)
$Folders = [ordered]@{
    Output = Join-Path $RootFolder 'Output'
    Done   = Join-Path $RootFolder 'Done'
    Failed = Join-Path $RootFolder 'Failed'
    Logs   = Join-Path $RootFolder 'Logs'
    Work   = Join-Path $RootFolder '_work'
}
foreach ($f in $Folders.Values) { [void][IO.Directory]::CreateDirectory($f) }

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ZipBase = [IO.Path]::GetFileNameWithoutExtension($ZipPath)
$LogFile = Join-Path $Folders.Logs "$ZipBase $Stamp.log"
$script:PbiPid = $null
$script:PbiExe = $null
$script:WorkDir = $null
$script:EnginePort = $null
$script:EngineClient = 'unknown'      # 'loaded' | 'missing'
$script:FrontWarned = $false

function Write-Log([string] $Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Message
    [IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, [Text.Encoding]::UTF8)
    Write-Host $line
}

function Write-Result([string] $Text) {
    if ($ResultFile) {
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $ResultFile))
        [IO.File]::WriteAllText($ResultFile, $Text, (New-Object Text.UTF8Encoding($false)))
    }
}

function Get-FreeFolder([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Path }
    for ($i = 2; $i -lt 1000; $i++) {
        $candidate = "$Path ($i)"
        if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "No free folder name for $Path"
}

function Get-FreeFile([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Path }
    $dir = [IO.Path]::GetDirectoryName($Path)
    $base = [IO.Path]::GetFileNameWithoutExtension($Path)
    $ext = [IO.Path]::GetExtension($Path)
    for ($i = 2; $i -lt 1000; $i++) {
        $candidate = Join-Path $dir "$base ($i)$ext"
        if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "No free file name for $Path"
}

function Test-IsUnder([string] $Path, [string] $Folder) {
    $p = [IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    $f = [IO.Path]::GetFullPath($Folder).TrimEnd('\') + '\'
    return $p.StartsWith($f, [StringComparison]::OrdinalIgnoreCase)
}

# ================================================================ Windows helpers

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

if (-not ('PbixBotWin32' -as [type])) {
    Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class PbixBotWin32 {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, StringBuilder l);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
    [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr h);
    [DllImport("user32.dll")] static extern int GetDlgCtrlID(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetDlgItem(IntPtr dialog, int id);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }

    const int WM_GETTEXT = 0x000D, WM_GETTEXTLENGTH = 0x000E, WM_COMMAND = 0x0111;
    const int CB_GETCOUNT = 0x0146, CB_GETLBTEXT = 0x0148, CB_GETLBTEXTLEN = 0x0149, CB_SETCURSEL = 0x014E;
    const int CBN_SELCHANGE = 1, CBN_CLOSEUP = 8, CBN_SELENDOK = 9, IDOK = 1;

    public static string ClassOf(IntPtr h) {
        var sb = new StringBuilder(256);
        GetClassName(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static string GetText(IntPtr h) {
        int n = (int)SendMessage(h, WM_GETTEXTLENGTH, IntPtr.Zero, IntPtr.Zero);
        var sb = new StringBuilder(n + 2);
        SendMessage(h, WM_GETTEXT, (IntPtr)(n + 1), sb);
        return sb.ToString();
    }

    public static string[] ComboItems(IntPtr combo) {
        int count = Math.Max(0, (int)SendMessage(combo, CB_GETCOUNT, IntPtr.Zero, IntPtr.Zero));
        var items = new string[count];
        for (int i = 0; i < count; i++) {
            int len = Math.Max(0, (int)SendMessage(combo, CB_GETLBTEXTLEN, (IntPtr)i, IntPtr.Zero));
            var sb = new StringBuilder(len + 2);
            SendMessage(combo, CB_GETLBTEXT, (IntPtr)i, sb);
            items[i] = sb.ToString();
        }
        return items;
    }

    // Select an item and send the notifications a real pick from the drop-down sends.
    // The Save As dialog only takes the new file type on board when it gets all three.
    public static void PickComboItem(IntPtr combo, int index) {
        SendMessage(combo, CB_SETCURSEL, (IntPtr)index, IntPtr.Zero);
        IntPtr parent = GetParent(combo);
        int id = GetDlgCtrlID(combo) & 0xFFFF;
        foreach (int code in new[] { CBN_SELENDOK, CBN_SELCHANGE, CBN_CLOSEUP })
            SendMessage(parent, WM_COMMAND, (IntPtr)((code << 16) | id), combo);
    }

    // Same as clicking the dialog's Save button.
    public static void PressOk(IntPtr dialog) {
        PostMessage(dialog, WM_COMMAND, (IntPtr)IDOK, GetDlgItem(dialog, IDOK));
    }

    public static bool BringToFront(IntPtr h) {
        if (IsIconic(h)) ShowWindow(h, 9);                       // SW_RESTORE
        if (GetForegroundWindow() == h) return true;
        SetForegroundWindow(h);
        if (GetForegroundWindow() == h) return true;
        // Windows only lets the window that has the keyboard hand it over: borrow its input queue.
        uint fg = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero);
        uint me = GetCurrentThreadId();
        if (fg != 0 && fg != me && AttachThreadInput(me, fg, true)) {
            SetForegroundWindow(h);
            BringWindowToTop(h);
            AttachThreadInput(me, fg, false);
        }
        return GetForegroundWindow() == h;
    }

    // A picture of one window only (even when other windows cover it).
    public static bool SaveWindowImage(IntPtr h, string path) {
        RECT r;
        if (!GetWindowRect(h, out r)) return false;
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        if (w <= 0 || ht <= 0) return false;
        using (var bmp = new System.Drawing.Bitmap(w, ht)) {
            using (var g = System.Drawing.Graphics.FromImage(bmp)) {
                IntPtr hdc = g.GetHdc();
                bool ok;
                try { ok = PrintWindow(h, hdc, 2); } finally { g.ReleaseHdc(hdc); }   // PW_RENDERFULLCONTENT
                if (!ok) return false;
            }
            bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        }
        return true;
    }
}
'@
}

function New-Cond($Property, $Value) { New-Object System.Windows.Automation.PropertyCondition -ArgumentList $Property, $Value }

# First element with this exact name (and control type), preferring visible ones.
function Find-Named($Root, [string] $Name, [string] $Type) {
    if (-not $Root) { return $null }
    $fallback = $null
    foreach ($e in $Root.FindAll($TS::Descendants, (New-Cond $AE::NameProperty $Name))) {
        try {
            $c = $e.Current
            if ($Type -and $c.ControlType.ProgrammaticName -ne "ControlType.$Type") { continue }
            if (-not $c.IsOffscreen) { return $e }
            if (-not $fallback) { $fallback = $e }
        } catch { continue }
    }
    return $fallback
}

function Get-Texts($Root) {
    $names = @()
    if (-not $Root) { return $names }
    $cond = New-Cond $AE::ControlTypeProperty ([System.Windows.Automation.ControlType]::Text)
    foreach ($e in $Root.FindAll($TS::Descendants, $cond)) {
        try { $n = $e.Current.Name; if ($n) { $names += $n.Trim() } } catch { }
    }
    return $names
}

function Invoke-Element($Element, [string] $What) {
    $p = $null
    if ($Element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$p)) { $p.Invoke(); return }
    if ($Element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$p)) { $p.Select(); return }
    if ($Element.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$p)) { $p.Expand(); return }
    throw "$What offers no way to press it"
}

function Assert-PowerBIRunning {
    if ($script:PbiPid -and -not (Get-Process -Id $script:PbiPid -ErrorAction SilentlyContinue)) {
        throw 'Power BI Desktop closed unexpectedly.'
    }
}

# Re-runs $Condition until it returns something, or throws after $TimeoutSeconds.
function Wait-Until([scriptblock] $Condition, [int] $TimeoutSeconds, [string] $What, [int] $PollMilliseconds = 1000) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ($true) {
        $result = & $Condition
        if ($result) { return $result }
        if ((Get-Date) -gt $deadline) { throw "Timed out after $TimeoutSeconds s waiting for $What." }
        Assert-PowerBIRunning
        Start-Sleep -Milliseconds $PollMilliseconds
    }
}

# Finds an element with $Finder and presses it. Power BI's screens are web pages that redraw
# often, so a button found a moment ago can be gone: on failure, find it again and retry.
function Press([scriptblock] $Finder, [string] $What, [int] $TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ($true) {
        Assert-PowerBIRunning
        try {
            $element = & $Finder
            if ($element) { Invoke-Element $element $What; return }
        } catch { $lastError = $_.Exception.Message }
        if ((Get-Date) -gt $deadline) { break }
        Start-Sleep -Milliseconds 1500
    }
    if ($lastError) { throw "Could not press $What in Power BI Desktop ($lastError)." }
    throw "Could not find $What in Power BI Desktop."
}

# ================================================================ Power BI Desktop

function Resolve-PbiDesktop([string] $Hint) {
    $candidates = @()
    if ($Hint) { $candidates += $Hint }
    foreach ($pf in @($env:ProgramW6432, $env:ProgramFiles)) {
        if ($pf) { $candidates += (Join-Path $pf 'Microsoft Power BI Desktop\bin\PBIDesktop.exe') }
    }
    try {
        $appPath = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PBIDesktop.exe' -ErrorAction Stop).'(default)'
        if ($appPath) { $candidates += $appPath.Trim('"') }
    } catch { }
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    throw 'Power BI Desktop was not found. Install it from the Microsoft Download Center (the Store version cannot be started this way), or pass -PbiDesktopPath.'
}

function Get-PbiMainWindow {
    if (-not $script:PbiPid) { return $null }
    foreach ($w in $AE::RootElement.FindAll($TS::Children, (New-Cond $AE::ProcessIdProperty $script:PbiPid))) {
        try { if ($w.Current.ClassName -like 'WindowsForms10.Window*') { return $w } } catch { }
    }
    return $null
}

function Show-PowerBI {
    $main = Get-PbiMainWindow
    if (-not $main) { return }
    try { $main.SetFocus() } catch { }
    if (-not [PbixBotWin32]::BringToFront([IntPtr]$main.Current.NativeWindowHandle) -and -not $script:FrontWarned) {
        $script:FrontWarned = $true
        Write-Log 'Could not bring Power BI Desktop to the front; carrying on behind other windows'
    }
}

function Save-PowerBIImage {
    $main = Get-PbiMainWindow
    if (-not $main) { return }
    $path = Join-Path $Folders.Logs "$ZipBase $Stamp.png"
    try {
        if ([PbixBotWin32]::SaveWindowImage([IntPtr]$main.Current.NativeWindowHandle, $path)) { Write-Log "Picture of the Power BI window: $path" }
    } catch { }
}

function Start-PowerBI([string] $Pbip) {
    $p = Start-Process -FilePath $script:PbiExe -ArgumentList ('"' + $Pbip + '"') -PassThru
    $script:PbiPid = $p.Id
    $script:EnginePort = $null
    Write-Log "Started Power BI Desktop (process $($p.Id))"
}

function Stop-PowerBI {
    if (-not $script:PbiPid) { return }
    if (Get-Process -Id $script:PbiPid -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $script:PbiPid /T /F 2>&1 | Out-Null
        Write-Log "Stopped Power BI Desktop (process $script:PbiPid)"
    }
    $script:PbiPid = $null
}

function Close-PowerBI {
    if (-not $script:PbiPid) { return }
    $proc = Get-Process -Id $script:PbiPid -ErrorAction SilentlyContinue
    if (-not $proc) { $script:PbiPid = $null; return }
    $main = Get-PbiMainWindow
    if ($main) {
        try { $main.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close() } catch { }
    }
    if (-not $proc.WaitForExit(60000)) {
        # A "save your changes?" prompt: the .pbix is already saved, so don't save again.
        $main = Get-PbiMainWindow
        if ($main) {
            $cond = New-Cond $AE::ControlTypeProperty ([System.Windows.Automation.ControlType]::Button)
            foreach ($b in $main.FindAll($TS::Descendants, $cond)) {
                try { if ($b.Current.Name -like "Don*t save") { Invoke-Element $b "Don't save"; break } } catch { }
            }
        }
        if (-not $proc.WaitForExit(60000)) { Stop-PowerBI; return }
    }
    Write-Log 'Closed Power BI Desktop'
    $script:PbiPid = $null
}

function Find-RibbonRefresh($Main) {
    if (-not $Main) { return $null }
    foreach ($e in $Main.FindAll($TS::Descendants, (New-Cond $AE::NameProperty 'Refresh'))) {
        try {
            $c = $e.Current
            if ($c.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $c.ClassName -like '*splitPrimaryButton*' -and $c.IsEnabled) { return $e }
        } catch { }
    }
    return $null
}

function Test-NoDataBanner($Main) {
    foreach ($t in (Get-Texts $Main)) { if ($t -like 'Some of the tables have incomplete or no data*') { return $true } }
    return $false
}

# ---------------------------------------------------------------- Power BI's data engine
# Power BI Desktop runs its own Analysis Services engine (msmdsrv.exe). Asking it which tables
# hold data tells us the refresh worked, whatever the screen shows.

function Initialize-EngineClient {
    if ($script:EngineClient -eq 'loaded') { return $true }
    if ($script:EngineClient -eq 'missing') { return $false }
    try {
        Add-Type -Path (Join-Path (Split-Path -Parent $script:PbiExe) 'Microsoft.PowerBI.AdomdClient.dll')
        $script:EngineClient = 'loaded'
        return $true
    } catch {
        $script:EngineClient = 'missing'
        Write-Log "Could not load Power BI's data engine client ($($_.Exception.Message)); checking the screen instead"
        return $false
    }
}

function Get-EnginePort {
    if ($script:EnginePort) { return $script:EnginePort }
    foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name = 'msmdsrv.exe'" -ErrorAction SilentlyContinue)) {
        if ($p.ParentProcessId -ne $script:PbiPid) { continue }
        if ($p.CommandLine -match '-s\s+"([^"]+)"') {
            $file = Join-Path $Matches[1] 'msmdsrv.port.txt'
            if (Test-Path -LiteralPath $file) {
                $bytes = [IO.File]::ReadAllBytes($file)
                if ($bytes -contains 0) { $text = [Text.Encoding]::Unicode.GetString($bytes) } else { $text = [Text.Encoding]::ASCII.GetString($bytes) }
                $digits = $text -replace '\D', ''
                if ($digits) { $script:EnginePort = [int]$digits; return $script:EnginePort }
            }
        }
    }
    return $null
}

function Invoke-EngineQuery([string] $Query) {
    $port = Get-EnginePort
    if (-not $port) { throw "Power BI's data engine is not running yet." }
    $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
    $conn.Open()
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $Query
        $cmd.CommandTimeout = 60
        $reader = $cmd.ExecuteReader()
        $rows = New-Object System.Collections.Generic.List[object]
        while ($reader.Read()) {
            $values = New-Object object[] $reader.FieldCount
            [void]$reader.GetValues($values)
            $rows.Add($values)
        }
        $reader.Close()
        return , $rows.ToArray()
    } finally { $conn.Close() }
}

# The names of tables that hold no data yet (a partition not in the "Ready" state).
function Get-TablesNotLoaded {
    $names = @{}
    foreach ($r in (Invoke-EngineQuery 'SELECT [ID], [Name] FROM $SYSTEM.TMSCHEMA_TABLES')) { $names["$($r[0])"] = "$($r[1])" }
    $notLoaded = @()
    foreach ($r in (Invoke-EngineQuery 'SELECT [TableID], [State] FROM $SYSTEM.TMSCHEMA_PARTITIONS')) {
        if ([int]$r[1] -ne 1) { $notLoaded += $names["$($r[0])"] }     # 1 = Ready
    }
    return , @($notLoaded | Select-Object -Unique)
}

function Get-RowCounts {
    $tables = @()
    foreach ($r in (Invoke-EngineQuery 'SELECT [Name] FROM $SYSTEM.TMSCHEMA_TABLES')) {
        $n = "$($r[0])"
        if ($n -notlike 'LocalDateTable_*' -and $n -notlike 'DateTableTemplate_*') { $tables += $n }
    }
    if ($tables.Count -eq 0) { return '' }
    $rows = foreach ($t in $tables) { 'ROW("Table", "' + $t.Replace('"', '""') + '", "Rows", COUNTROWS(''' + $t.Replace("'", "''") + '''))' }
    if ($tables.Count -eq 1) { $dax = "EVALUATE $rows" } else { $dax = 'EVALUATE UNION(' + ($rows -join ', ') + ')' }
    $parts = foreach ($r in (Invoke-EngineQuery $dax)) {
        if ($r[1] -is [DBNull] -or $null -eq $r[1]) { $count = 0 } else { $count = [long]$r[1] }
        '{0} {1:n0}' -f $r[0], $count
    }
    return ($parts -join '; ')
}

# ---------------------------------------------------------------- open, refresh, save

# Waits until the report has loaded. Returns 'banner' when the "no data" banner with its
# "Refresh now" button is up (a project without cached data), else 'ribbon' (Home > Refresh).
function Wait-ReportReady {
    $script:RibbonSeenAt = $null
    $script:BannerChecks = 0
    $script:Shown = $false
    Wait-Until {
        $main = Get-PbiMainWindow
        if (-not $main) { return $null }
        if (-not $script:Shown) { Show-PowerBI; $script:Shown = $true }
        if (Find-Named $main 'Refresh now' 'Button') {
            $script:BannerChecks++
            if ($script:BannerChecks -ge 3) { return 'banner' }    # there on three checks in a row
            return $null
        }
        $script:BannerChecks = 0
        if (Find-RibbonRefresh $main) {
            if (-not $script:RibbonSeenAt) { $script:RibbonSeenAt = Get-Date }
            elseif (((Get-Date) - $script:RibbonSeenAt).TotalSeconds -ge 30) { return 'ribbon' }
        }
        return $null
    } $OpenTimeoutSeconds 'the report to open in Power BI Desktop' 2000
}

function Invoke-Refresh([string] $Kind) {
    if ($Kind -eq 'banner') {
        $finder = { Find-Named (Get-PbiMainWindow) 'Refresh now' 'Button' }
        $minWait = 10
        Write-Log 'Refreshing the data (Refresh now)'
    } else {
        $finder = { Find-RibbonRefresh (Get-PbiMainWindow) }
        $minWait = 30
        Write-Log 'Refreshing the data (Home > Refresh)'
    }
    $useEngine = Initialize-EngineClient
    $hadBanner = Test-NoDataBanner (Get-PbiMainWindow)
    Show-PowerBI
    $started = Get-Date
    Press $finder 'Refresh'
    $presses = 1
    $sawDialog = $false
    $quietSince = $null
    $missingSince = $null
    $engineErrors = 0
    $busyPattern = 'Loading|rows loaded|Evaluating|Creating connection|Waiting|Applying|Processing|Refreshing|Calculat|Preparing'
    while ($true) {
        Start-Sleep -Seconds 2
        Assert-PowerBIRunning
        $elapsed = ((Get-Date) - $started).TotalSeconds
        if ($elapsed -gt $RefreshTimeoutSeconds) { throw "The refresh took longer than $RefreshTimeoutSeconds seconds." }
        $main = Get-PbiMainWindow
        if (-not $main) { continue }

        # While it loads, Power BI shows a "Load" dialog with progress; it closes when done.
        # If a table fails, the dialog stays open with the error and a Close button.
        $dialog = Find-Named $main 'Load' 'Window'
        if (-not $dialog) { $dialog = Find-Named $main 'Refresh' 'Window' }
        if ($dialog) {
            if (-not $sawDialog) { Write-Log 'Refresh running' }
            $sawDialog = $true
            $texts = @(Get-Texts $dialog)
            if ($texts -match $busyPattern) { $quietSince = $null; continue }
            if (-not $quietSince) { $quietSince = Get-Date; continue }
            $quiet = ((Get-Date) - $quietSince).TotalSeconds
            $hasClose = [bool](Find-Named $dialog 'Close' 'Button')
            if (($hasClose -and $quiet -ge 20) -or $quiet -ge 300) {
                $detail = ($texts | Where-Object { $_ -and $_ -notmatch '^(Load|Refresh|Close|Cancel)$' } | Select-Object -Unique) -join ' | '
                throw "The refresh stopped with errors: $detail"
            }
            continue
        }

        # No refresh dialog on screen: which tables still have no data?
        if ($useEngine) {
            try { $missing = Get-TablesNotLoaded; $engineErrors = 0 }
            catch {
                # engine busy: look again; if it keeps failing, judge by the screen instead
                $engineErrors++
                if ($engineErrors -lt 15) { continue }
                Write-Log "Could not ask Power BI's data engine ($($_.Exception.Message)); checking the screen instead"
                $useEngine = $false
                continue
            }
        } else {
            if (Test-NoDataBanner $main) { $missing = @('(the "no data" banner is still showing)') } else { $missing = @() }
        }
        if ($missing.Count -eq 0) {
            if ($sawDialog -or $hadBanner -or $elapsed -ge $minWait) { break }
            continue
        }
        if ($sawDialog) {
            # the refresh ran: give the engine (or the banner) a moment to catch up
            if (-not $missingSince) { $missingSince = Get-Date }
            elseif (((Get-Date) - $missingSince).TotalSeconds -ge 15) {
                throw ('The refresh finished, but these tables have no data: ' + ($missing -join ', '))
            }
        }
        elseif ($elapsed -ge (20 * $presses)) {
            # the press did not take (the page was redrawing): press again while the button is there
            if ($presses -ge 3) { throw 'The refresh did not start.' }
            if (& $finder) {
                Write-Log 'The refresh has not started yet; pressing Refresh again'
                Show-PowerBI
                Press $finder 'Refresh'
                $presses++
            }
        }
    }
    Write-Log ('Refresh finished in {0:n0} s' -f ((Get-Date) - $started).TotalSeconds)
    if ($useEngine) {
        try { Write-Log ('Rows loaded: ' + (Get-RowCounts)) } catch { }
    }
}

function Get-DialogFolder($Dialog, [string] $Fallback) {
    $cond = New-Cond $AE::ClassNameProperty 'ToolbarWindow32'
    foreach ($e in $Dialog.FindAll($TS::Descendants, $cond)) {
        try {
            if ($e.Current.Name -match '^[^:]+:\s*(.+)$') {
                $p = $Matches[1].Trim()
                if (Test-Path -LiteralPath $p -PathType Container) { return $p }
            }
        } catch { }
    }
    return $Fallback
}

function Test-PbixComplete([string] $Path) {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try { return [bool]($zip.Entries | Where-Object { $_.FullName -eq 'DataModel' -or $_.FullName -like 'Report/*' }) }
        finally { $zip.Dispose() }
    } catch { return $false }
}

# File > Save as > Browse this device > "Power BI file (*.pbix)" > Save. Returns the saved path.
function Save-AsPbix([string] $ProjectDir) {
    Show-PowerBI
    # File > Save as (press File again if the menu did not open)
    $fileFinder = { $m = Get-PbiMainWindow; if ($m) { $m.FindFirst($TS::Descendants, (New-Cond $AE::AutomationIdProperty 'Ribbon-file')) } }
    $saveAsFinder = { Find-Named (Get-PbiMainWindow) 'Save as' 'TabItem' }
    $opened = $false
    for ($try = 1; $try -le 3 -and -not $opened; $try++) {
        Press $fileFinder 'File'
        try { [void](Wait-Until $saveAsFinder 10 'File > Save as'); $opened = $true } catch { Write-Log 'The File menu did not open; trying again' }
    }
    if (-not $opened) { throw 'Could not open File > Save as in Power BI Desktop.' }
    Press $saveAsFinder 'Save as'
    Press { Find-Named (Get-PbiMainWindow) 'Browse this device' 'Button' } 'Browse this device'

    $dialog = Wait-Until {
        $m = Get-PbiMainWindow
        if ($m) { $m.FindFirst($TS::Descendants, (New-Cond $AE::ClassNameProperty '#32770')) }
    } 60 'the Save As dialog'
    $hDialog = [IntPtr]$dialog.Current.NativeWindowHandle
    Start-Sleep -Milliseconds 500

    # "Save as type": choose "Power BI file (*.pbix)"
    $typeHost = $dialog.FindFirst($TS::Descendants, (New-Cond $AE::AutomationIdProperty 'FileTypeControlHost'))
    if (-not $typeHost) { throw 'The "Save as type" list was not found in the Save As dialog.' }
    $hType = [IntPtr]$typeHost.Current.NativeWindowHandle
    if ([PbixBotWin32]::ClassOf($hType) -ne 'ComboBox') { $hType = [PbixBotWin32]::FindWindowEx($hType, [IntPtr]::Zero, 'ComboBox', $null) }
    if ($hType -eq [IntPtr]::Zero) { throw 'The "Save as type" list was not found in the Save As dialog.' }
    $items = [PbixBotWin32]::ComboItems($hType)
    $index = -1
    for ($i = 0; $i -lt $items.Length; $i++) { if ($items[$i].Contains('*.pbix')) { $index = $i; break } }
    if ($index -lt 0) { throw "The Save As dialog offers no .pbix type (it offers: $($items -join '; '))." }
    [PbixBotWin32]::PickComboItem($hType, $index)

    # The file name follows the type: "<Report>.pbix", in the project's folder
    $nameEdit = $null
    foreach ($e in $dialog.FindAll($TS::Descendants, (New-Cond $AE::AutomationIdProperty '1001'))) {
        try { if ($e.Current.ClassName -eq 'Edit') { $nameEdit = $e; break } } catch { }
    }
    if (-not $nameEdit) { throw 'The "File name" box was not found in the Save As dialog.' }
    $hName = [IntPtr]$nameEdit.Current.NativeWindowHandle
    $fileName = Wait-Until { $t = [PbixBotWin32]::GetText($hName); if ($t -like '*.pbix') { $t } } 10 'the file name to change to .pbix'

    $folder = Get-DialogFolder $dialog $ProjectDir
    if ([IO.Path]::IsPathRooted($fileName)) { $target = $fileName } else { $target = Join-Path $folder $fileName }
    if (-not (Test-IsUnder $target $script:WorkDir)) {
        throw "Power BI wanted to save outside the converter's work folder ($target); stopped to be safe."
    }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }

    Write-Log "Saving as $target"
    [PbixBotWin32]::PressOk($hDialog)
    [void](Wait-Until { -not [PbixBotWin32]::IsWindow($hDialog) } 60 'the Save As dialog to close')

    # Wait until the file is complete: same size twice in a row and a readable zip. Power BI's own error box (it does
    # not expose its text) stops the wait at once.
    $deadline = (Get-Date).AddSeconds($SaveTimeoutSeconds)
    $lastSize = -1
    while ($true) {
        Assert-PowerBIRunning
        $main = Get-PbiMainWindow
        if ($main) {
            $oops = $null
            try { $oops = $main.FindFirst($TS::Children, (New-Cond $AE::NameProperty 'Something went wrong')) } catch { }
            if ($oops) { throw 'Power BI Desktop could not save the .pbix: it showed "Something went wrong".' }
        }
        if (Test-Path -LiteralPath $target) {
            $size = (Get-Item -LiteralPath $target).Length
            if ($size -gt 0 -and $size -eq $lastSize -and (Test-PbixComplete $target)) { break }
            $lastSize = $size
        }
        if ((Get-Date) -gt $deadline) { throw "Power BI did not finish saving $target within $SaveTimeoutSeconds s." }
        Start-Sleep -Seconds 2
    }
    return $target
}

# ================================================================ project handling

function Get-SemanticModelDir([IO.FileInfo] $Pbip) {
    $projDir = $Pbip.DirectoryName
    try {
        $pbipJson = Get-Content -LiteralPath $Pbip.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $reportDir = Join-Path $projDir (@($pbipJson.artifacts)[0].report.path)
        $pbir = Get-Content -LiteralPath (Join-Path $reportDir 'definition.pbir') -Raw -Encoding UTF8 | ConvertFrom-Json
        $rel = $pbir.datasetReference.byPath.path
        if ($rel) {
            $dir = [IO.Path]::GetFullPath((Join-Path $reportDir $rel))
            if (Test-Path -LiteralPath $dir -PathType Container) { return $dir }
        }
    } catch { }
    $name = [IO.Path]::GetFileNameWithoutExtension($Pbip.Name)
    $dir = Join-Path $projDir "$name.SemanticModel"
    if (Test-Path -LiteralPath $dir -PathType Container) { return $dir }
    $any = Get-ChildItem -LiteralPath $projDir -Directory -Filter '*.SemanticModel' | Select-Object -First 1
    if ($any) { return $any.FullName }
    return $null
}

# Points the model's DataFolder parameter at $NewFolder. Returns the old value, or $null if
# the model has no such parameter. Handles model.bim (TMSL) and definition\expressions.tmdl.
function Set-DataFolderParameter([string] $SemanticModelDir, [string] $NewFolder) {
    if (-not $SemanticModelDir) { return $null }
    if (-not $NewFolder.EndsWith('\')) { $NewFolder += '\' }
    $newM = $NewFolder.Replace('"', '""')                 # M text literal
    $utf8 = New-Object Text.UTF8Encoding($false)

    $bim = Join-Path $SemanticModelDir 'model.bim'
    if (Test-Path -LiteralPath $bim) {
        $raw = [IO.File]::ReadAllText($bim)
        $model = $raw | ConvertFrom-Json
        $expr = @($model.model.expressions) | Where-Object { $_ -and $_.name -eq 'DataFolder' } | Select-Object -First 1
        if (-not $expr) { return $null }
        $m = @($expr.expression) -join "`n"
        $match = [regex]::Match($m, '^\s*"((?:[^"]|"")*)"')
        if (-not $match.Success) { throw "The DataFolder parameter is not a plain text value: $m" }
        $oldM = $match.Groups[1].Value
        # Edit the JSON text in place: only this value changes, the rest of the file stays as it was
        $oldJson = '\"' + $oldM.Replace('\', '\\').Replace('"', '\"') + '\"'
        $newJson = '\"' + $newM.Replace('\', '\\').Replace('"', '\"') + '\"'
        if (-not $raw.Contains($oldJson)) { throw 'Could not find the DataFolder value in model.bim.' }
        [IO.File]::WriteAllText($bim, $raw.Replace($oldJson, $newJson), $utf8)
        return $oldM.Replace('""', '"')
    }

    $tmdl = Join-Path $SemanticModelDir 'definition\expressions.tmdl'
    if (Test-Path -LiteralPath $tmdl) {
        $raw = [IO.File]::ReadAllText($tmdl)
        $match = [regex]::Match($raw, '(?m)^\s*expression\s+''?DataFolder''?\s*=\s*"((?:[^"]|"")*)"')
        if (-not $match.Success) { return $null }
        $g = $match.Groups[1]
        [IO.File]::WriteAllText($tmdl, $raw.Substring(0, $g.Index) + $newM + $raw.Substring($g.Index + $g.Length), $utf8)
        return $g.Value.Replace('""', '"')
    }
    return $null
}

function Convert-Project([IO.FileInfo] $Pbip) {
    $name = [IO.Path]::GetFileNameWithoutExtension($Pbip.Name)
    $projDir = $Pbip.DirectoryName
    $outDir = Get-FreeFolder (Join-Path $Folders.Output $name)
    [void][IO.Directory]::CreateDirectory($outDir)
    Write-Log "Report '$name' -> $outDir"
    try {
        # 1. The data: copy the CSVs next to the .pbix (or under -DataRoot) and point the model at them
        if ($DataSource) { $dataSrc = $DataSource } else { $dataSrc = Join-Path $projDir 'data' }
        if (-not (Test-Path -LiteralPath $dataSrc -PathType Container)) { $dataSrc = Join-Path $script:WorkDir 'data' }
        if (Test-Path -LiteralPath $dataSrc -PathType Container) {
            if ($DataRoot) {
                # the caller's own folder for this report (pbix.ps1 owns <DataRoot>): a copy left by an earlier run goes
                $outData = Join-Path (Join-Path $DataRoot $name) 'data'
                if (Test-Path -LiteralPath $outData) { Remove-Item -LiteralPath $outData -Recurse -Force }
                [void][IO.Directory]::CreateDirectory((Split-Path -Parent $outData))
            }
            else { $outData = Join-Path $outDir 'data' }
            Copy-Item -LiteralPath $dataSrc -Destination $outData -Recurse -Force
            $count = @(Get-ChildItem -LiteralPath $outData -Recurse -File).Count
            Write-Log "Copied $count data file(s) to $outData"
            $old = Set-DataFolderParameter (Get-SemanticModelDir $Pbip) $outData
            if ($old) { Write-Log "DataFolder parameter: $old -> $outData\" }
            else { Write-Log 'The model has no DataFolder parameter; it keeps its own data sources.' }
        }
        else { Write-Log 'The zip has no data folder; the model keeps its own data sources.' }

        # 2. Open, refresh, save as .pbix, close
        $target = Join-Path $outDir "$name.pbix"
        Start-PowerBI $Pbip.FullName
        try {
            $refreshKind = Wait-ReportReady
            Write-Log 'Report open'
            Start-Sleep -Seconds 3
            Invoke-Refresh $refreshKind
            $saved = Save-AsPbix $projDir
            Close-PowerBI
        }
        catch {
            Save-PowerBIImage
            Stop-PowerBI
            throw
        }
        Move-Item -LiteralPath $saved -Destination $target
    }
    catch {
        # leave no half-made report in Output
        Remove-Item -LiteralPath $outDir -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
    Write-Log ('Saved {0} ({1:n1} MB)' -f $target, ((Get-Item -LiteralPath $target).Length / 1MB))
    return $target
}

function Copy-Report([IO.FileInfo] $Pbix) {
    $name = [IO.Path]::GetFileNameWithoutExtension($Pbix.Name)
    $outDir = Get-FreeFolder (Join-Path $Folders.Output $name)
    [void][IO.Directory]::CreateDirectory($outDir)
    $target = Join-Path $outDir $Pbix.Name
    Copy-Item -LiteralPath $Pbix.FullName -Destination $target
    $dataSrc = Join-Path $Pbix.DirectoryName 'data'
    if (Test-Path -LiteralPath $dataSrc -PathType Container) { Copy-Item -LiteralPath $dataSrc -Destination (Join-Path $outDir 'data') -Recurse -Force }
    Write-Log "The zip already holds a .pbix; copied it to $target"
    return $target
}

# ================================================================ main

$exitCode = 1
$mutex = New-Object System.Threading.Mutex($false, 'Local\PbixBot-Convert')
$haveMutex = $false
try {
    Write-Log "Zip: $ZipPath"
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { throw "The zip file does not exist: $ZipPath" }

    # One conversion at a time: Power BI Desktop is heavy and the dialogs must not mix.
    try { $haveMutex = $mutex.WaitOne([TimeSpan]::FromMinutes(30)) } catch [System.Threading.AbandonedMutexException] { $haveMutex = $true }
    if (-not $haveMutex) { throw 'Another conversion has been running for 30 minutes; try again later.' }

    # Wait for the zip to be completely copied into the inbox (it opens once nobody writes to it)
    [void](Wait-Until {
        try { $s = [IO.File]::Open($ZipPath, 'Open', 'Read', 'None'); $s.Close(); $true } catch { $false }
    } 120 'the zip to finish copying')

    # Remove work folders left by failed runs more than 3 days ago
    Get-ChildItem -LiteralPath $Folders.Work -Directory | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-3) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

    $script:WorkDir = Get-FreeFolder (Join-Path $Folders.Work $Stamp)
    [void][IO.Directory]::CreateDirectory($script:WorkDir)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $script:WorkDir)
    Write-Log "Unzipped to $script:WorkDir"

    $pbips = @(Get-ChildItem -LiteralPath $script:WorkDir -Recurse -File -Filter '*.pbip')
    $pbixes = @(Get-ChildItem -LiteralPath $script:WorkDir -Recurse -File -Filter '*.pbix')
    if ($pbips.Count -eq 0 -and $pbixes.Count -eq 0) { throw 'The zip holds nothing Power BI Desktop can open.' }

    $results = @()
    if ($pbips.Count -gt 0) {
        $script:PbiExe = Resolve-PbiDesktop $PbiDesktopPath
        Write-Log "Power BI Desktop: $script:PbiExe"
        foreach ($p in $pbips) { $results += Convert-Project $p }
    }
    else {
        foreach ($p in $pbixes) { $results += Copy-Report $p }
    }

    $doneZip = Get-FreeFile (Join-Path $Folders.Done ([IO.Path]::GetFileName($ZipPath)))
    Move-Item -LiteralPath $ZipPath -Destination $doneZip
    Write-Log "Zip moved to $doneZip"
    Write-Result (@('OK') + $results -join [Environment]::NewLine)
    Write-Log 'Done'
    $exitCode = 0
}
catch {
    $reason = $_.Exception.Message
    Write-Log "FAILED: $reason"
    if ($_.InvocationInfo) { Write-Log ('  at line {0}: {1}' -f $_.InvocationInfo.ScriptLineNumber, $_.InvocationInfo.Line.Trim()) }
    Stop-PowerBI
    try {
        if (Test-Path -LiteralPath $ZipPath) {
            $failedZip = Get-FreeFile (Join-Path $Folders.Failed ([IO.Path]::GetFileName($ZipPath)))
            Move-Item -LiteralPath $ZipPath -Destination $failedZip
            Write-Log "Zip moved to $failedZip"
        }
    } catch { Write-Log "Could not move the zip to Failed: $($_.Exception.Message)" }
    Write-Result ('FAILED{0}{1}{0}Log: {2}' -f [Environment]::NewLine, $reason, $LogFile)
}
finally {
    if ($script:WorkDir -and (Test-Path -LiteralPath $script:WorkDir)) {
        if ($exitCode -eq 0 -and -not $KeepWorkFolder) {
            Remove-Item -LiteralPath $script:WorkDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        else { Write-Log "Work folder kept for checking: $script:WorkDir" }
    }
    if ($haveMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $exitCode
