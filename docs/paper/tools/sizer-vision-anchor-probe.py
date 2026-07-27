#!/usr/bin/env python3
"""Reproduce the `sizer` (keyhole-sizer) Case 1 measurement, independently.

WHY THIS FILE EXISTS
--------------------
`95emulator`'s Risk-1 review of the ieee-paper argued that first-person
`cases_*.md` essays are the weakest evidence class for the paper's strongest
claims, and that a claim tagged RECORD-DERIVED must actually resolve to
"a commit, bus-line, or probe someone else can run, or the tag is just a
nicer-looking assertion."

This is that probe, for Case 1. It takes no argument on faith and asks nothing
of my narration. Point it at the keyhole-sizer repo and it reports whether the
vision measured-anchor bug is present, on whatever engine version is installed.

WHAT IT MEASURES
----------------
keyhole-sizer projects vision latency per (tier x pipeline x resolution). A
memory-upgrade tier is a `dataclass` CLONE of a measured tier, produced by
`hw_with_memory()`, carrying `bw_projected=True` and `stock_mem_bandwidth_gbs`.

For a bandwidth-bound workload the clone's measured anchor MUST be scaled by the
bandwidth ratio -- fps scales directly, ms inversely -- and, because the clone is
a part that was never built and never measured, its provenance badge MUST
degrade from `measured` to `same_class_anchor`.

Two invariants, checked on every clone cell that has a measured vision anchor:

    I1   fps_ratio(clone/stock)  ==  bw_ratio(clone/stock)     (exactly)
    I2   edge_ms_source(clone)   ==  "same_class_anchor"        (not "measured")

RESULT ON THE RECORD
--------------------
    at commit e0c3d08 (and for the 46 days before it):    0 / 129 cells pass
    at commit b80b83f (v2.0.1) and later:               129 / 129 cells pass

Both numbers are reproducible with this script by checking out either commit.
The pre-fix state additionally showed every clone cell reporting a *flat* ms
identical to stock while bandwidth rose by up to 2.19x, badged `measured`.

PROVENANCE / DISCLOSURE
-----------------------
Prints RATIOS AND COUNTS ONLY. keyhole-sizer's absolute anchor magnitudes are
private measured silicon values kept in a gitignored `.streamlit/secrets.toml`
and treated as credentials, so no magnitude is emitted here. The invariants are
scale-free, so nothing is lost.

Note: the cells this probe exercises (NPU Low-LP5X, NPU i.MX 95) carry anchors
that live in COMMITTED code, not in secrets -- so this reproduces with no
credentials present at all.

USAGE
-----
    python sizer-vision-anchor-probe.py /path/to/keyhole-sizer

    # to see the defect rather than the fix:
    git -C /path/to/keyhole-sizer stash        # if dirty
    git -C /path/to/keyhole-sizer checkout e0c3d08
    python sizer-vision-anchor-probe.py /path/to/keyhole-sizer
    git -C /path/to/keyhole-sizer checkout -

Exit code 0 = both invariants hold everywhere (fix present).
Exit code 1 = at least one violation (defect present). Either is a valid result;
the exit code is for scripting, not a judgement.
"""
import sys
import os

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo = os.path.abspath(sys.argv[1])
    if not os.path.isdir(os.path.join(repo, "sizer")):
        print(f"ERROR: {repo} does not look like keyhole-sizer (no sizer/ package)")
        return 2

    sys.path.insert(0, repo)
    os.chdir(repo)  # anchors load relative to cwd

    try:
        import ratchet
        engine = getattr(ratchet, "__version__", "?")
    except Exception:
        engine = "(ratchet not importable)"

    from sizer.npu_model import (TIERS, PIPELINES, MEMORY_UPGRADE_OPTIONS,
                                 hw_with_memory, project_vision)

    print(f"repo   : {repo}")
    print(f"engine : ratchet {engine}")
    print("(ratios only -- no anchor magnitudes are printed)\n")

    passed = failed = 0
    violations = []

    for tier_name, tier in TIERS.items():
        overrides = tier.measured_vision_overrides or {}
        for pipeline_key in sorted(overrides):
            if pipeline_key not in PIPELINES:
                continue                      # anchor for a pipeline not in this catalog
            for resolution in sorted(overrides[pipeline_key]):
                try:
                    stock = project_vision(PIPELINES[pipeline_key], tier, resolution)
                except Exception:
                    continue                  # resolution not projectable for this pipeline
                for label, mem_type, gtps in MEMORY_UPGRADE_OPTIONS:
                    clone = hw_with_memory(tier, mem_type, gtps)
                    got = project_vision(PIPELINES[pipeline_key], clone, resolution)

                    bw_ratio = clone.mem_bandwidth_gbs / tier.mem_bandwidth_gbs
                    fps_ratio = got["fps_per_stream"] / stock["fps_per_stream"]
                    i1 = abs(fps_ratio - bw_ratio) < 1e-9
                    i2 = got["edge_ms_source"] == "same_class_anchor"

                    if i1 and i2:
                        passed += 1
                    else:
                        failed += 1
                        violations.append(dict(
                            tier=tier_name, pipeline=pipeline_key, res=resolution,
                            upgrade=label, fps_ratio=round(fps_ratio, 4),
                            bw_ratio=round(bw_ratio, 4),
                            badge=got["edge_ms_source"], I1=i1, I2=i2,
                            flat=abs(fps_ratio - 1.0) < 1e-9,
                        ))

    total = passed + failed
    print(f"RESULT: {passed}/{total} clone cells satisfy BOTH invariants\n")

    if violations:
        flat = sum(1 for v in violations if v["flat"])
        mislabelled = sum(1 for v in violations if not v["I2"])
        worst = max(violations, key=lambda v: v["bw_ratio"])
        print(f"  cells whose fps is FLAT despite more bandwidth : {flat}")
        print(f"  cells badged 'measured' on an unbuilt clone    : {mislabelled}")
        print(f"  worst case: {worst['tier']} / {worst['pipeline']} @ {worst['res']}"
              f" + {worst['upgrade']}")
        print(f"             fps_ratio={worst['fps_ratio']} vs bw_ratio={worst['bw_ratio']}"
              f"  badge={worst['badge']}")
        understated = 100 * (1 - 1 / worst["bw_ratio"])
        print(f"             => understates achievable fps by {understated:.1f}%\n")
        print("  first 5 violations:")
        for v in violations[:5]:
            print(f"    {v['tier']:28s} {v['pipeline']:26s} {v['res']:6s} {v['upgrade']:22s}"
                  f" fps_ratio={v['fps_ratio']:<7} bw_ratio={v['bw_ratio']:<7} badge={v['badge']}")
        return 1

    print("  Both invariants hold on every clone cell: anchors bandwidth-scale,")
    print("  and no derived clone claims the 'measured' badge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
