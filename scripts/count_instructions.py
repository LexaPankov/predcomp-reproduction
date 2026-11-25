#!/usr/bin/env python3
"""
Count executed instructions (and cycles) for PredComp's sequences and for -O3.

Suggested by Prof. De Sensi: the number of executed instructions does not depend on
the CPU frequency, which we cannot fix on the cluster, so it gives a second,
frequency-independent view of what the compiler options change.
Note that fewer instructions does not always mean faster (e.g. vectorization or
memory effects), so this complements the timing results, it does not replace them.

Uses the same build commands and output check as measure.py, then runs
`perf stat -e instructions:u,cycles:u -r N` on each binary (user-space only,
pinned to one core). perf follows the child processes started by __run.

Example
  python3 count_instructions.py --cbench ~/PredComp/Dataset/cBench_V1.1 \
      --program all --from-log ~/logs/full_run_docker.log --out results/instr_gcc9
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure  # noqa: E402  (build commands, program table, log reader, environment)

# perf binary to use: inside our Ubuntu 20.04 container, /usr/bin/perf is a wrapper that refuses
# to run on a newer host kernel, so the job script points PERF at the real binary.
PERF = os.environ.get("PERF", "perf")


def parse_perf_csv(text):
    """Parse `perf stat -x,` output: returns {event: value} (None if not counted)."""
    vals = {}
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        value, event = parts[0].strip(), parts[2].strip()
        for name in ("instructions", "cycles"):
            if event.startswith(name):
                try:
                    vals[name] = float(value)
                except ValueError:          # "<not supported>" / "<not counted>"
                    vals[name] = None
    return vals


def count(src, core, repeats):
    p = measure.sh(f"taskset -c {core} {PERF} stat -x, -r {repeats} -e instructions:u,cycles:u -- ./__run 1 >/dev/null", src)
    vals = parse_perf_csv(p.stderr)
    if p.returncode != 0 or vals.get("instructions") is None:
        raise RuntimeError(p.stderr.strip()[-600:] or "perf failed")
    return vals


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cbench", required=True)
    ap.add_argument("--program", required=True, help="program name(s), comma-separated, or 'all'")
    ap.add_argument("--from-log", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--cc", default="gcc")
    ap.add_argument("--core", type=int, default=2)
    ap.add_argument("--repeats", type=int, default=3, help="perf -r: runs averaged per binary (instruction counts barely vary)")
    a = ap.parse_args()
    a.out = os.path.abspath(os.path.expanduser(a.out))
    os.makedirs(a.out, exist_ok=True)

    from_log = {}
    for path in a.from_log:
        from_log.update(measure.read_log(os.path.expanduser(path)))
    progs = sorted(from_log) if a.program == "all" else [x.strip() for x in a.program.split(",") if x.strip()]

    # stop early with a clear message if perf cannot count instructions here
    probe = measure.sh(f"{PERF} stat -x, -e instructions:u -- true", ".")
    if parse_perf_csv(probe.stderr).get("instructions") is None:
        sys.exit("perf cannot count instructions on this machine:\n" + probe.stderr.strip()[-600:])

    with open(os.path.join(a.out, "environment.json"), "w") as f:
        json.dump(measure.environment(a.cc), f, indent=2)

    rows = []
    for prog in progs:
        src = os.path.join(os.path.expanduser(a.cbench), prog, "src")
        configs = {"O3": "-O3"}
        for i, s in enumerate(from_log.get(prog, []), 1):
            configs[f"top{i}"] = s
        print(f"\n=== {prog}", flush=True)
        res = {}
        ref_ok = False
        for label, flags in configs.items():
            if os.path.lexists(os.path.join(src, "a.out")):
                os.remove(os.path.join(src, "a.out"))
            p = measure.build(src, a.cc, flags, prog)
            if p.returncode != 0:
                rows.append({"program": prog, "config": label, "status": "compile_error", "flags": flags})
                print(f"  {label}: compile error", flush=True)
                continue
            md5 = measure.md5(os.path.join(src, "a.out"))
            if label == "O3":                       # reference output, as in measure.py
                measure.sh("./_ccc_check_output.clean", src)
                measure.run_once(src, a.core, "wall")
                measure.sh("./_ccc_check_output.copy", src)
                ref_ok = True
            elif ref_ok:
                measure.run_once(src, a.core, "wall")
                diff = measure.sh("./_ccc_check_output.diff; cat tmp-ccc-diff", src).stdout.strip()
                if diff and prog not in measure.NO_OUTPUT_CHECK:
                    rows.append({"program": prog, "config": label, "status": "wrong_output", "flags": flags})
                    print(f"  {label}: wrong output", flush=True)
                    continue
            v = count(src, a.core, a.repeats)
            res[label] = v
            r = {"program": prog, "config": label, "status": "ok", "instructions": int(v["instructions"]),
                 "cycles": int(v["cycles"]) if v.get("cycles") else "", "binary_md5": md5, "flags": flags}
            if v.get("cycles"):
                r["ipc"] = round(v["instructions"] / v["cycles"], 4)
            rows.append(r)
            print(f"  {label}: {v['instructions']:.4g} instructions", flush=True)
        if "O3" in res:
            for r in rows:
                if r["program"] == prog and r.get("status") == "ok":
                    r["instr_ratio_O3_over_config"] = round(res["O3"]["instructions"] / r["instructions"], 4)
                    if r.get("cycles") and res["O3"].get("cycles"):
                        r["cycles_ratio_O3_over_config"] = round(res["O3"]["cycles"] / r["cycles"], 4)

    cols = ["program", "config", "status", "instructions", "cycles", "ipc", "instr_ratio_O3_over_config",
            "cycles_ratio_O3_over_config", "binary_md5", "flags"]
    with open(os.path.join(a.out, "instructions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nsaved: {a.out}/instructions.csv")
    print("INSTR_DONE")


if __name__ == "__main__":
    main()
