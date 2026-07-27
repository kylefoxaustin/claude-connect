#!/usr/bin/env python3
"""Held-constant memory measurement harness for long-running processes.

Written for the `jaws` ieee-paper case (docs/paper/cases_jaws.md); shared because the
discipline generalises to any "does this process consume what it claims" question.

WHY IT EXISTS — three ways the cheap version lies:

  * Sampling RSS in a loop SYSTEMATICALLY UNDERESTIMATES THE PEAK — **EXERCISED, not
    asserted**: 40/40 trials on this host underestimated it and 0/40 caught it in full.
    A 50 MB transient against this file's own 50 ms poll showed 28.6 of 74.8 MB (62%
    under; worst trial 66%); a 400 MB transient showed 360.5 of 424.7 MB (15% under;
    worst 40%). So the error grows as the transient shrinks.
    ⚠ CORRECTION TO AN EARLIER VERSION OF THIS DOCSTRING: it claimed a sub-interval
    transient is "invisible" to polling. That was FALSE and had never been tested —
    0/40 trials were invisible. Making pages resident takes time proportional to size,
    so a spike RAMPS and a poller always catches part of it. The defect is an
    UNDERESTIMATE, not a blind spot. (The false version shipped because it was
    plausible and unexercised — the same failure this file is meant to prevent.)
    This reads /proc/<pid>/status **VmHWM**, the kernel's own peak-RSS high-water mark,
    so the peak is a reading rather than a sample.
  * "It looked settled" is not a settle criterion. Here a run is settled only when VmRSS
    moves < PLATEAU_TOL_KB for PLATEAU_S seconds, with a floor and a hard cap.
  * `timeout N` without -k is a REQUEST a wedged child never services, and `$!` on
    `timeout ... &` is the wrapper's pid, so killing it ORPHANS the child. This kills the
    child's whole process GROUP with SIGKILL, waits, then re-reads /proc to PROVE the pid
    is gone, and prints that proof per run (alive_after_kill=False).

WHAT IT DOES NOT DO: census the host. Take one separately (a CPU delta over a real
interval, binaries resolved via /proc/PID/exe) and record it WITH the numbers — a shared
box biases every figure here, and that looks exactly like "slower than you thought."

USAGE:
    ./mem-measure-harness.py OUTDIR '[{"label":"v2_1pct",
                                       "argv":["python3","jaws.py","--percent","1","--static"],
                                       "target_mb":963.33}]'

Writes OUTDIR/out_<label>.log per run and OUTDIR/results.json for all runs.

⚠ RUN EVERY CONFIG AT TWO DIFFERENT TARGETS. A single point cannot distinguish an
additive overhead from a multiplicative one — which is the exact error this harness was
built after committing (see cases_jaws.md, Case 3).
"""
import json
import os
import signal
import subprocess
import sys
import time

POLL = 0.05
PLATEAU_S = 3.0
PLATEAU_TOL_KB = 1024
MIN_RUN_S = 6.0
HARD_CAP_S = 240.0
FIELDS = ("VmRSS", "VmHWM", "VmLck", "VmSwap", "VmSize")


def status(pid):
    out = {}
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                for k in FIELDS:
                    if line.startswith(k + ":"):
                        out[k] = int(line.split()[1])  # kB
    except (FileNotFoundError, ProcessLookupError):
        return None
    return out


def run(outdir, label, argv, target_mb):
    print(f"\n{'='*72}\n{label}\n  cmd: {' '.join(argv)}\n{'='*72}", flush=True)
    log = open(os.path.join(outdir, f"out_{label}.log"), "wb")
    # start_new_session => own process group, so we can kill the whole tree.
    p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    pid = p.pid
    t0 = time.time()
    last_rss, last_change, peak_seen = -1, t0, 0
    final = None
    try:
        while True:
            now = time.time()
            s = status(pid)
            if s is None:
                print(f"  child exited early (rc={p.poll()}) — see out_{label}.log")
                break
            peak_seen = max(peak_seen, s.get("VmHWM", 0))
            rss = s.get("VmRSS", 0)
            if abs(rss - last_rss) > PLATEAU_TOL_KB:
                last_rss, last_change = rss, now
            elapsed = now - t0
            if elapsed > MIN_RUN_S and (now - last_change) > PLATEAU_S:
                final = s
                break
            if elapsed > HARD_CAP_S:
                print("  HARD CAP hit — recording anyway (treat as unsettled)")
                final = s
                break
            time.sleep(POLL)
    finally:
        # Reap what we started, and PRINT the corpse check.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("  !! child did not die on SIGKILL — investigate before trusting numbers")
        log.close()
        print(f"  corpse check: pid {pid} alive_after_kill={status(pid) is not None}")

    if final is None:
        return None
    hwm = max(peak_seen, final.get("VmHWM", 0))
    res = {
        "label": label, "target_mb": target_mb, "argv": argv,
        "peak_mb": hwm / 1024, "rss_mb": final.get("VmRSS", 0) / 1024,
        "lck_mb": final.get("VmLck", 0) / 1024,
        "swap_mb": final.get("VmSwap", 0) / 1024,
        "vsz_mb": final.get("VmSize", 0) / 1024,
        "settle_s": time.time() - t0,
    }
    whole_as = (res["lck_mb"] > 0 and abs(res["lck_mb"] - res["vsz_mb"]) < 1)
    print(f"  target      : {target_mb:9.1f} MB")
    print(f"  PEAK (VmHWM): {res['peak_mb']:9.1f} MB   -> {res['peak_mb']/target_mb:5.2f}x target")
    print(f"  plateau RSS : {res['rss_mb']:9.1f} MB   -> {res['rss_mb']/target_mb:5.2f}x target")
    print(f"  VmLck       : {res['lck_mb']:9.1f} MB"
          f"{'   <-- == VmSize: WHOLE address space locked' if whole_as else ''}")
    print(f"  VmSwap      : {res['swap_mb']:9.1f} MB")
    print(f"  VmSize(virt): {res['vsz_mb']:9.1f} MB")
    print(f"  settle      : {res['settle_s']:9.1f} s")
    return res


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    outdir, cases = sys.argv[1], json.loads(sys.argv[2])
    os.makedirs(outdir, exist_ok=True)
    results = []
    for c in cases:
        r = run(outdir, c["label"], c["argv"], c["target_mb"])
        if r:
            results.append(r)
        time.sleep(2.0)  # let the box settle between runs
    print("\n\n=== SUMMARY ===")
    print(f"{'case':28} {'target':>9} {'peak':>10} {'x':>6} {'rss':>10} {'lck':>9} {'swap':>7}")
    for r in results:
        print(f"{r['label']:28} {r['target_mb']:9.1f} {r['peak_mb']:10.1f} "
              f"{r['peak_mb']/r['target_mb']:6.2f} {r['rss_mb']:10.1f} "
              f"{r['lck_mb']:9.1f} {r['swap_mb']:7.1f}")
    path = os.path.join(outdir, "results.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
