<#
.SYNOPSIS
  Make a Windows box able to run Conductor's bash gates, and PROVE it before saying so.

.DESCRIPTION
  The gates (bus/persist-gate.sh, bus/push-gate.sh) run their whole decision through a
  Python interpreter. On Windows that is not free:

    * The python.org / winget install ships python.exe and pythonw.exe. It does NOT ship
      a `python3`. The literal string the gates reach for does not exist.
    * `C:\Users\<you>\AppData\Local\Microsoft\WindowsApps\python3.exe` is a ZERO-BYTE
      Microsoft Store App Execution Alias. It satisfies `where`, `command -v`, Test-Path
      and every existence check there is, and exits 9009 (49 under Git Bash) when run.
      It has never been an interpreter.

  Since 1fad8bd the gates fail CLOSED when they cannot find one, which is correct and is
  why this script matters: without a usable interpreter the gates still protect you, but
  they deny the whole false-positive class as well -- transcripts under ~/.claude/projects,
  bus-state (which the gate's own comment says is "written constantly by everyone; gating
  it would break the fleet and protect nothing"), and even reads of gated paths. Safe, but
  blunt in exactly the high-frequency places.

  So this is a PRECONDITION for the gates on Windows, not a convenience.

  MEASURED on Windows 11 / Git Bash 5.3, 2026-08-23: with CLAUDE_BUS_PYTHON set, all eight
  acceptance payloads below behave identically to Linux. Without it, four of eight deny.

.NOTES
  Two rules this script follows, both learned the hard way on this port:

    1. NEVER conclude an interpreter is usable because it RESOLVES. Run it. The Store
       stub is the counterexample and it is on PATH by default on every Windows box.
    2. NEVER report success from "the install command exited 0". Verify by running the
       REAL gate against payloads with known-correct verdicts. A check that cannot
       observe the thing it claims to check is a green light with nothing behind it.

.PARAMETER Scope
  Where to record CLAUDE_BUS_PYTHON. 'User' (default) writes ~/.claude/settings.json and
  applies to every session. 'Project' writes .claude/settings.json next to the repo.

.PARAMETER SkipInstall
  Probe and verify only. Never invokes winget. Use to check an existing box.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap-windows.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet('User','Project')] [string] $Scope = 'User',
    [switch] $SkipInstall,
    # Arm the push gate globally (installs the pre-push hook + sets core.hooksPath).
    # OFF by default and it stays off until the verification below passes -- see step 5.
    [switch] $ArmPushGate
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Say  { param($m) Write-Host "  $m" }
function Head { param($m) Write-Host "`n== $m" -ForegroundColor Cyan }
function Bad  { param($m) Write-Host "  $m" -ForegroundColor Red }
function Good { param($m) Write-Host "  $m" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# Is this candidate an INTERPRETER, or something that merely resolves like one?
# The gate bodies import json/os/re/sys, so probe with exactly that: a python too
# old or too stripped fails here, where we can name it, rather than mid-parse where
# it is indistinguishable from "nothing matched".
# ---------------------------------------------------------------------------
function Test-Interpreter {
    param([string] $Exe, [string[]] $Prefix = @())
    if (-not $Exe) { return $null }
    try {
        # Two traps, both found by running this against a python that demonstrably works:
        #
        #   1. NOT $args -- that is a PowerShell automatic variable, and assigning to it
        #      here silently breaks the splat.
        #   2. The probe snippet contains NO string literal ON PURPOSE. PowerShell strips
        #      quotes when passing arguments to a native exe, so `sys.stdout.write("X:"+p)`
        #      arrives at python as `sys.stdout.write(X:+p)` -- a SyntaxError, which reads
        #      as "this interpreter is broken" when the interpreter is fine.
        #
        # So: the imports are the real test, and the proof of life is a non-empty path on
        # stdout with exit 0. Nothing to quote, nothing to strip.
        $argv = @($Prefix) + @('-c', 'import json,os,re,sys; sys.stdout.write(sys.executable)')
        $out  = & $Exe @argv 2>&1
        if ($LASTEXITCODE -ne 0) { return $null }
        $line = ($out | Out-String).Trim()
        if ($line -and $line -notmatch '\r?\n' -and (Test-Path -LiteralPath $line)) { return $line }
        return $null
    } catch { return $null }
}

function Find-UsableInterpreter {
    # Order matters: an explicitly recorded absolute path wins over anything on PATH,
    # because PATH is what a venv or a re-enabled Store alias can shadow tomorrow.
    $candidates = @()
    if ($env:CLAUDE_BUS_PYTHON) { $candidates += ,@($env:CLAUDE_BUS_PYTHON, @()) }
    $candidates += ,@((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'), @())
    $candidates += ,@((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), @())
    $candidates += ,@('python3', @())
    $candidates += ,@('python',  @())
    $candidates += ,@('py',      @('-3'))

    foreach ($c in $candidates) {
        $exe, $prefix = $c
        $resolved = Test-Interpreter -Exe $exe -Prefix $prefix
        if ($resolved) { return [pscustomobject]@{ Probe = $exe; Real = $resolved } }
        # Say WHY it was rejected -- a silent skip here is how the stub wins.
        $found = (Get-Command $exe -ErrorAction SilentlyContinue)
        if ($found) { Say "rejected  $exe -> resolves ($($found.Source)) but does not run" }
    }
    return $null
}

# ---------------------------------------------------------------------------
# settings.json: MERGE. Never replace -- this file may already carry the user's
# hooks, permissions and plugins, and clobbering it to set one variable would be
# a far bigger act than the one being asked for.
# ---------------------------------------------------------------------------
function Set-BusPython {
    param([string] $Path, [string] $Value)
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

    $obj = [ordered]@{}
    if (Test-Path $Path) {
        $raw = Get-Content -Raw -Encoding UTF8 $Path
        if ($raw.Trim()) {
            try { $existing = $raw | ConvertFrom-Json }
            catch { throw "REFUSING to write: $Path is not valid JSON. Fix it first -- a malformed settings.json silently disables EVERY setting in it, which would be a worse outcome than the problem this script solves." }
            foreach ($p in $existing.PSObject.Properties) { $obj[$p.Name] = $p.Value }
        }
        Copy-Item $Path "$Path.bak" -Force
        Say "backed up -> $Path.bak"
    }

    $env_ = [ordered]@{}
    if ($obj.Contains('env') -and $obj['env']) {
        foreach ($p in $obj['env'].PSObject.Properties) { $env_[$p.Name] = $p.Value }
    }
    $env_['CLAUDE_BUS_PYTHON'] = $Value
    $obj['env'] = $env_

    ($obj | ConvertTo-Json -Depth 64) | Set-Content -Path $Path -Encoding UTF8
    return $Path
}

# ---------------------------------------------------------------------------
# The acceptance test. NOT "did the install exit 0" -- run the real gate against
# payloads whose correct verdicts are known, including the false-positive class,
# which is the half that a merely-safe gate gets wrong.
# ---------------------------------------------------------------------------
# Feed a hook payload on stdin with NO BOM and no re-encoding, and return the real exit
# code. PowerShell 5.1 has no `<` redirection and its native-pipe path adds a BOM, so the
# only faithful way to reproduce what Claude Code hands a hook is to drive the process
# directly and write the bytes ourselves.
function Invoke-GateWithStdin {
    param([string] $BashExe, [string] $Gate, [string] $Payload, [switch] $Bom)
    # Stdin is taken out of the picture ENTIRELY: the payload goes to a file written as raw
    # BOM-less bytes, and bash redirects from it. Three ways of piping were tried first and
    # all three put a UTF-8 BOM at byte 0 -- `$x | & bash` does, and so does writing to
    # StandardInput.BaseStream, because the StreamWriter emits its preamble when closed.
    # json.loads raises on a leading BOM, so the gate degraded and DENIED, which looks
    # exactly like the gate being broken. A file has no encoding negotiation to lose.
    $pf   = [System.IO.Path]::GetTempFileName()
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $bytes = $utf8.GetBytes($Payload)
    # -Bom deliberately puts the BOM back, for the regression row that pins the utf-8-sig
    # fix. Everywhere else it stays off, because an accidental BOM is the bug, not the test.
    if ($Bom) { $bytes = ([byte[]](0xEF,0xBB,0xBF)) + $bytes }
    [System.IO.File]::WriteAllBytes($pf, $bytes)
    $mGate = '/' + ($Gate -replace '^([A-Za-z]):','$1' -replace '\\','/')
    $mPf   = '/' + ($pf   -replace '^([A-Za-z]):','$1' -replace '\\','/')

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $BashExe
    $psi.Arguments              = '-c "' + ('"' + $mGate + '" < "' + $mPf + '"').Replace('"','\"') + '"'
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute        = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    $so = $p.StandardOutput.ReadToEnd()
    $se = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    Remove-Item $pf -Force -ErrorAction SilentlyContinue
    # Return the output too. A verifier that can report only PASS/FAIL cannot tell you
    # whether the gate disagreed with you or crashed, and those need opposite responses.
    return [pscustomobject]@{ Code = $p.ExitCode; Out = $so; Err = $se }
}

function Test-GateBehaviour {
    param([string] $BashExe, [string] $BusPython)

    $gate = Join-Path $RepoRoot 'bus\persist-gate.sh'
    if (-not (Test-Path $gate)) { Say "SKIPPED: $gate not found"; return $null }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("condboot-" + [guid]::NewGuid().ToString('N').Substring(0,8))
    foreach ($d in '.claude\bin','.claude\commands','.claude\bus-state\registry','.claude\projects','coord','proj') {
        New-Item -ItemType Directory -Force -Path (Join-Path $tmp $d) | Out-Null
    }

    # THE TABLE IS NOT DEFINED HERE. It lives in tests/gate_acceptance.json and is driven
    # by tests/test_gate_acceptance.py on Linux as well, so a verdict cannot drift on one
    # platform without the other going red, and neither platform owns the truth.
    # Add cases to the JSON, never to this file.
    $tablePath = Join-Path $RepoRoot 'tests\gate_acceptance.json'
    if (-not (Test-Path $tablePath)) { Say "SKIPPED: $tablePath not found"; return $null }
    $table = Get-Content -Raw -Encoding UTF8 $tablePath | ConvertFrom-Json

    # verdict 2 = DENY, 0 = ALLOW
    # Substitute the table's placeholders with THIS sandbox's Windows paths. The POSIX
    # spelling is provided too, for the rows that deliberately probe the other namespace.
    $chPosix = '/' + (($tmp -replace '^([A-Za-z]):','$1') -replace '\\','/') + '/.claude'
    $vals = @{
        TMP       = $tmp
        CH        = (Join-Path $tmp '.claude')
        PROJ      = (Join-Path $tmp 'proj')
        CH_POSIX  = $chPosix
    }
    function Sub($s) { foreach ($k in $vals.Keys) { $s = $s.Replace('{' + $k + '}', $vals[$k]) }; return $s }

    # Build one payload. ConvertTo-Json is a REAL serializer -- hand-built JSON with Windows
    # backslashes throws in json.loads and looks exactly like the bug under test.
    function Build($case) {
        if ($case.PSObject.Properties.Name -contains 'raw_stdin' -and $case.raw_stdin) {
            return (Sub $case.raw_stdin)
        }
        $inp = @{}
        foreach ($pp in $case.input.PSObject.Properties) { $inp[$pp.Name] = (Sub $pp.Value) }
        return (@{ cwd = $vals.PROJ; tool_name = $case.tool; tool_input = $inp } |
                ConvertTo-Json -Compress -Depth 8)
    }

    # BUS_STATE_DIR is set EXPLICITLY. The gate derives it from $HOME otherwise, and Git Bash
    # rewrites HOME into an MSYS path on the way in ('C:\...\x' arrives as '/tmp/x'), so the
    # sandbox and the thing under test end up disagreeing about where state lives -- which
    # showed up as "no gate.log written" while the gate had been writing one all along.
    $envBlock = @{
        COORD_STATE_DIR   = (Join-Path $tmp 'coord')
        CLAUDE_CONFIG_DIR = (Join-Path $tmp '.claude')
        BUS_STATE_DIR     = (Join-Path $tmp '.claude\bus-state')
        HOME              = $tmp
        # ⚠️ BOTH, and it is not belt-and-braces. MEASURED: os.path.expanduser on Windows
        # IGNORES $HOME and honours $USERPROFILE. The gate has two halves -- bash expands `~`
        # from $HOME, its embedded python expands it with expanduser -- so sandboxing only HOME
        # leaves the python half resolving `~` to the REAL profile of whoever runs this script.
        # The tilde row then evaluated against the developer's actual ~/.claude, found no
        # matching prefix, and the gate correctly ALLOWED -- reported here as "the gate is
        # broken on Windows" when the harness was.
        #
        # tests/test_gate_acceptance.py fixed exactly this on its own fixture and this copy did
        # not follow, so the two harnesses driving the SAME shared table disagreed about the same
        # row: pytest said DENY, the bootstrap said ALLOW. That disagreement is the only reason
        # it was found. USERPROFILE has now broken four separate suites; it is worth a line in
        # CLAUDE.md rather than a fifth rediscovery.
        USERPROFILE       = $tmp
        CLAUDE_BUS_PYTHON = $BusPython
    }
    $saved = @{}
    foreach ($k in $envBlock.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k) }
    foreach ($k in $envBlock.Keys) { [Environment]::SetEnvironmentVariable($k, $envBlock[$k]) }

    $pass = 0; $fail = 0
    try {
        foreach ($c in $table.cases) {
            $payload = Build $c
            $bom = ($c.PSObject.Properties.Name -contains 'stdin_bom' -and $c.stdin_bom)
            # ⚠️ NOT `$payload | & $BashExe`. PowerShell's UTF-8 $OutputEncoding prepends a
            # BOM when piping to a native exe -- measured: 144 chars in, 146 out, leading
            # ﻿ -- and json.loads raises on that. The gate then (correctly) denies an
            # unparseable payload, which reads as "the gate is broken" when the harness is.
            # Worth knowing beyond this script: Claude Code runs shell-form hooks through
            # PowerShell when Git Bash is absent, so a BOM-prefixed payload is reachable in
            # production on such a box, not just in tests.
            $res = Invoke-GateWithStdin -BashExe $BashExe -Gate $gate -Payload $payload -Bom:$bom
            $rc  = $res.Code
            $got = if ($rc -eq 2) { 'DENY' } elseif ($rc -eq 0) { 'ALLOW' } else { "rc=$rc" }
            $want = if ($c.expect -eq 'deny') { 2 } else { 0 }
            $exp = $c.expect.ToUpper()
            if ($rc -eq $want) { $pass++; Good ("ok  {0,-42} {1}" -f $c.name, $got) }
            else {
                $fail++; Bad ("!!  {0,-42} {1}  (expected {2})" -f $c.name, $got, $exp)
                Bad ("      why this row exists: " + $c.why)
                $why = (($res.Out + $res.Err).Trim() -split "`r?`n" | Where-Object { $_ } | Select-Object -First 3)
                foreach ($w in $why) { Bad ("      | " + $w.Substring(0, [Math]::Min(96, $w.Length))) }
                if (-not $why) { Bad "      | (gate produced no output -- it did not think it was refusing)" }
            }
        }
        Write-Host ""
        Say "known gaps (reported, not counted -- the bootstrap cannot fix these):"
        foreach ($k in $table.known_gaps) {
            $rc  = (Invoke-GateWithStdin -BashExe $BashExe -Gate $gate -Payload (Build $k)).Code
            $got = if ($rc -eq 2) { 'DENY' } elseif ($rc -eq 0) { 'ALLOW' } else { "rc=$rc" }
            $want = if ($k.expect -eq 'deny') { 2 } else { 0 }
            if ($rc -eq $want) {
                # CLOSED where the table says it should be open: say so loudly. The row wants
                # moving into cases, and a silent pass would leave the table claiming a gap
                # that no longer exists.
                Good ("      CLOSED  {0,-38} {1}   <- move it into cases" -f $k.name, $got)
            } else {
                Write-Host ("      OPEN    {0,-38} {1}  (want {2})" -f $k.name, $got, $k.expect.ToUpper()) -ForegroundColor Yellow
                Write-Host ("              {0}" -f $k.why) -ForegroundColor DarkYellow
            }
        }
    } finally {
        # The gate logs a traceback here when it degrades. Surface it BEFORE deleting the
        # sandbox -- "the gate itself failed" tells you it crashed but not on what, and the
        # difference between a crash and a disagreement changes what you do next.
        if ($fail -gt 0) {
            $log = Join-Path $tmp '.claude\bus-state\gate.log'
            if (Test-Path $log) {
                Write-Host ""
                Say "gate.log (why it degraded):"
                Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue |
                    Select-Object -Last 12 | ForEach-Object { Bad ("      " + $_) }
            } else { Say "no gate.log written at $log" }
        }
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ Pass = $pass; Fail = $fail }
}

# ---------------------------------------------------------------------------
# THE PUSH GATE, and why "installed" is not the thing worth reporting
# ---------------------------------------------------------------------------
# skippy, 2026-08-30, on putting this in the bootstrap: "Manual-per-clone IS how a control ends
# up absent on exactly one box and nobody notices for three days" -- measured here, where the
# gate was missing on this machine while the fleet-wide claim was that every push is gated.
#
# And the half that matters more, their words: the bootstrap must VERIFY the gate, not just
# place the files. This file's own history is gates that were present and did not run --
# v2.34.1 shipped an armed persist-gate whose prefilter exited before the real check, twice --
# so "installed", asserted from a file existing, is exactly that class.
#
# ⭐ SO THIS VERIFIES BOTH DIRECTIONS, because a gate is a DOOR and a door that only ever shuts
# is not working either. Two probes, against a throwaway bare repo -- never a real remote:
#
#   DENY     an unapproved push must be refused and must land nothing
#   APPROVE  a token written the way CONDUCTOR writes it must let the push through
#
# The second probe exists because of what was measured on Windows on 2026-08-30: the token key
# is the repo path with '/' and space translated but NOT ':', so on this platform every key is
# `C:_Users_...`. MSYS writes that colon as U+F03A; native Python -- which is what Conductor is
# -- cannot stat the request and cannot create the token at all. The gate can DENY and nothing
# can APPROVE, so the inbox tap and the phone are both dead while the gate keeps printing "THE
# REQUEST IS NOW FILED" and telling the session to wait. A bootstrap that verified only the DENY
# would call that healthy and arm it.
function Test-PushGate {
    param([string] $BashExe, [string] $PythonExe)

    $hook = Join-Path $RepoRoot 'bus\git-hooks\pre-push'
    if (-not (Test-Path $hook)) { Say "SKIPPED: $hook not found"; return $null }

    $lab = Join-Path ([System.IO.Path]::GetTempPath()) ("condgate-" + [guid]::NewGuid().ToString('N').Substring(0,8))
    $coord = Join-Path $lab 'coord'
    $hooks = Join-Path $lab 'hooks'
    $work  = Join-Path $lab 'work'
    New-Item -ItemType Directory -Force -Path $coord, $hooks, $work | Out-Null
    $saved = $env:COORD_STATE_DIR
    $denied = $false; $approved = $false; $note = ''
    try {
        $env:COORD_STATE_DIR = $coord
        Copy-Item $hook (Join-Path $hooks 'pre-push') -Force
        git init --bare -q (Join-Path $lab 'target.git') | Out-Null
        Push-Location $work
        try {
            git init -q | Out-Null
            git remote add origin (Join-Path $lab 'target.git')
            git config user.email 'bootstrap@example.invalid'
            git config user.name  'bootstrap'
            # Repo-LOCAL hooksPath: the real hook, real refs, real stdin, and NOTHING global
            # touched. Arming is a separate, explicit act below.
            git config core.hooksPath $hooks
            'probe' | Out-File -FilePath (Join-Path $work 'f.txt') -Encoding utf8
            git add -A | Out-Null
            git commit -q -m 'probe' | Out-Null

            # --- probe 1: DENY -------------------------------------------------------------
            # ⚠️ NO `2>&1` on a native command here. In Windows PowerShell 5.1 that wraps each
            # stderr line in an ErrorRecord (NativeCommandError), and with the
            # $ErrorActionPreference = 'Stop' set at the top of this script it makes the GATE'S
            # OWN REFUSAL MESSAGE a terminating error -- so the probe died precisely when the
            # thing it is testing worked, and reported that as a bootstrap failure.
            $ErrorActionPreference = 'Continue'
            git push origin master 2>$null | Out-Null
            $landed = (git --git-dir=(Join-Path $lab 'target.git') log --oneline --all 2>$null)
            $denied = [string]::IsNullOrWhiteSpace($landed)

            # --- probe 2: can an approval be GRANTED the way Conductor grants one? ----------
            # Conductor is native Python, so the token is written by Python here on purpose.
            # Writing it from bash would prove only that bash agrees with bash.
            $repoTop = (git rev-parse --show-toplevel)
            $py = @"
import os, sys, time
repo, coord = sys.argv[1], sys.argv[2]
key = repo.replace('/', '_').replace(' ', '_').lstrip('_')
d = os.path.join(coord, 'push-tokens')
os.makedirs(d, exist_ok=True)
try:
    with open(os.path.join(d, key), 'w', encoding='utf-8') as f:
        f.write('expires=%d\n' % (int(time.time()) + 3600))
    print('WROTE')
except Exception as e:
    print('FAILED:%s:%s' % (type(e).__name__, e))
"@
            $pyFile = Join-Path $lab 'grant.py'
            $py | Out-File -FilePath $pyFile -Encoding utf8
            $grant = (& $PythonExe $pyFile $repoTop $coord 2>&1) -join ' '
            if ($grant -notmatch 'WROTE') {
                $note = "Conductor could not write the approval token: $grant"
            } else {
                git push origin master 2>$null | Out-Null
                $landed2 = (git --git-dir=(Join-Path $lab 'target.git') log --oneline --all 2>$null)
                $approved = -not [string]::IsNullOrWhiteSpace($landed2)
                if (-not $approved) { $note = 'the token was written but the push was still refused' }
            }
        } finally { Pop-Location }
    } finally {
        $env:COORD_STATE_DIR = $saved
        Remove-Item -Recurse -Force $lab -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ Denied = $denied; Approvable = $approved; Note = $note }
}

# ===========================================================================
Write-Host "Conductor - Windows bootstrap" -ForegroundColor White

Head "1. Git Bash (the shell Claude Code runs hooks through on Windows)"
$bash = $null
foreach ($p in @("$env:ProgramFiles\Git\bin\bash.exe", "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
                 "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe")) {
    if (Test-Path $p) { $bash = $p; break }
}
if (-not $bash) { $bash = (Get-Command bash.exe -ErrorAction SilentlyContinue).Source }
if (-not $bash) {
    Bad "NOT FOUND. Claude Code falls back to PowerShell for shell-form hooks when Git Bash"
    Bad "is absent, and every gate in bus/ is a bash script -- they would not run at all."
    Bad "Install it:  winget install Git.Git"
    exit 1
}
Good "found: $bash"
if ($env:PATH -notmatch [regex]::Escape((Split-Path $bash))) {
    Say "note: not on PATH. Claude Code finds it anyway, but `git push` from PowerShell will not."
}

Head "2. A Python that actually RUNS (not one that merely resolves)"
$interp = Find-UsableInterpreter
if (-not $interp -and -not $SkipInstall) {
    Say "no usable interpreter -- installing via winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Bad "winget is unavailable; install Python 3.12+ manually, then re-run."
        exit 1
    }
    # NOT --scope user: that variant skips the py launcher, which is one of the fallbacks.
    & winget install --id Python.Python.3.12 --source winget --silent `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    $interp = Find-UsableInterpreter
}
if (-not $interp) {
    Bad "STILL no usable interpreter. Not writing anything."
    Bad "The gates will fail CLOSED -- safe, but they will also deny transcripts,"
    Bad "bus-state and reads of gated paths. Fix Python before installing the hooks."
    exit 1
}
Good "usable: $($interp.Real)"
if ($interp.Probe -ne $interp.Real) { Say "(probed as '$($interp.Probe)')" }

Head "3. Record it where hooks can see it"
# MEASURED: settings.json's env block does reach a hook's environment (verified with a
# PreToolUse probe on this box, 2026-08-23). An absolute path is recorded rather than a
# PATH shim, because PATH is the thing that gets shadowed.
$settings = if ($Scope -eq 'User') { Join-Path $env:USERPROFILE '.claude\settings.json' }
            else { Join-Path (Split-Path -Parent $RepoRoot) '.claude\settings.json' }
$written = Set-BusPython -Path $settings -Value $interp.Real
Good "CLAUDE_BUS_PYTHON -> $written"

Head "4. Verify by RUNNING the real gate (not by trusting step 2)"
$r = Test-GateBehaviour -BashExe $bash -BusPython $interp.Real
if ($null -eq $r) {
    Say "gate not present in this checkout; interpreter is recorded but UNVERIFIED."
    exit 0
}
Write-Host ""
if ($r.Fail -ne 0) {
    Bad "$($r.Fail) of $($r.Pass + $r.Fail) payloads WRONG."
    Bad "CLAUDE_BUS_PYTHON is recorded but the gates do not behave correctly with it."
    Bad "Do NOT install the hooks until this is 0 -- report the failing rows."
    exit 1
}
Good "$($r.Pass)/$($r.Pass) acceptance payloads correct. Gates are usable on this box."

Head "5. Push gate: verify it can BOTH deny and be approved"
$g = Test-PushGate -BashExe $bash -PythonExe $interp.Real
if ($null -eq $g) {
    Say "push gate not present in this checkout; nothing to verify or arm."
} else {
    if ($g.Denied) { Good "DENY    an unapproved push was refused and landed nothing" }
    else           { Bad  "DENY    an unapproved push WAS NOT REFUSED" }

    if ($g.Approvable) { Good "APPROVE a Conductor-written token released the push" }
    else {
        Bad "APPROVE a Conductor-written token could NOT release the push"
        if ($g.Note) { Bad "        $($g.Note)" }
    }

    Write-Host ""
    if ($g.Denied -and $g.Approvable) {
        if ($ArmPushGate) {
            # Arming is GLOBAL and outlives this session, which is why it needs the flag AND a
            # passing verification. Never clobber an existing core.hooksPath -- that would
            # silently disable whatever else the human has installed there.
            $hookDir = Join-Path $env:USERPROFILE '.claude\git-hooks'
            New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
            Copy-Item (Join-Path $RepoRoot 'bus\git-hooks\pre-push') (Join-Path $hookDir 'pre-push') -Force
            $cur = (git config --global --get core.hooksPath 2>$null)
            if ([string]::IsNullOrWhiteSpace($cur)) {
                git config --global core.hooksPath $hookDir
                Good "ARMED: core.hooksPath -> $hookDir"
            } elseif ($cur -eq $hookDir) {
                Good "ARMED already: core.hooksPath -> $hookDir"
            } else {
                Bad "core.hooksPath is already '$cur' -- NOT overwriting it."
                Say "Drop bus\git-hooks\pre-push into that directory yourself (chain if one exists)."
            }
        } else {
            Say "Verified but NOT ARMED. Re-run with -ArmPushGate to install it globally."
        }
    } else {
        # skippy asked for this exact wording rather than a success line it has not earned.
        Bad "GATE NOT VERIFIED -- not arming, and -ArmPushGate will not override this."
        Say "A gate that denies but cannot be approved is a one-way door: the session is told"
        Say "to wait for a tap that cannot be delivered. Fix the approval path first."
        exit 1
    }
}

Write-Host ""
Say "Restart Claude Code (or open /hooks) so the new env is picked up by running sessions."
exit 0
