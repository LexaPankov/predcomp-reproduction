#!/usr/bin/env python3
"""
Count instructions and cycles of the EXACT binaries that measure.py timed.

measure.py keeps every binary it timed in <job>/bin/<program>/<config>.out and records
its MD5 in <job>/summary.csv. This script:

  1. checks that every saved binary still has the MD5 recorded in summary.csv, and aborts
     on any mismatch or missing file (this is what proves we count the timed binaries);
  2. runs each binary, pinned to one core, in interleaved rounds (new random order per round),
     under `perf stat -e instructions:u,cycles:u`, and records for every run:
       instructions, cycles (user space), wall time, user time and system time
     (user/sys from os.wait4 on the perf process, so they include perf's small overhead);
  3. sanity-checks the cycles: configurations that share one binary (same MD5) must agree
     within --cycles-tolerance (default 1%); if not, cycles should not be used.

No compiling and no output check: the binaries were already built and checked by measure.py.

Example (smoke test):
  python3 count_timed_binaries.py --cbench /tmp/cbench --job-dir ~/backup_results/cluster_gcc13_job1035048 \
      --out results/timed_counts_test --program telecom_CRC32 --rounds 2
"""
import argparse
import csv
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure  # noqa: E402  (md5, use_binary, environment)
from count_instructions import parse_perf_csv  # noqa: E402

PERF = os.environ.get("PERF", "perf")


def read_summary(job_dir):
    """{program: {config: md5}} for every configuration that was timed (status ok, md5 known)."""
    out = {}
    with open(os.path.join(job_dir, "summary.csv")) as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok" and r.get("binary_md5"):
                out.setdefault(r["program"], {})[r["config"]] = r["binary_md5"]
    return out


def check_binaries(job_dir, summary, progs):
    """Abort unless every saved binary exists and has the MD5 from summary.csv."""
    bins, problems = {}, []
    for prog in progs:
        for config, want in summary[prog].items():
            path = os.path.join(job_dir, "bin", prog, f"{config}.out")
            if not os.path.isfile(path):
                problems.append(f"missing: {path}")
                continue
            got = measure.md5(path)
            if got != want:
                problems.append(f"MD5 MISMATCH {prog} {config}: saved {got}, summary.csv {want}")
            bins[(prog, config)] = path
    if problems:
        print("\n".join(problems))
        sys.exit("ABORT: the saved binaries are not exactly the timed ones")
    print(f"MD5 check passed: {len(bins)} binaries match summary.csv", flush=True)
    return bins


def run_once(src, core):
    """One run under perf stat. Returns instructions, cycles, wall, user, sys."""
    fd, tmp = tempfile.mkstemp(suffix=".perf")
    os.close(fd)
    cmd = ["taskset", "-c", str(core), PERF, "stat", "-x,", "-o", tmp,
           "-e", "instructions:u,cycles:u", "--", "./__run", "1"]
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=src, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _, status, ru = os.wait4(p.pid, 0)
    wall = time.perf_counter() - t0
    p.returncode = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
    with open(tmp) as f:
        text = f.read()
    os.remove(tmp)
    vals = parse_perf_csv(text)
    if p.returncode != 0 or vals.get("instructions") is None or vals.get("cycles") is None:
        raise RuntimeError(f"perf failed (exit {p.returncode}): {text.strip()[-400:]}")
    return {"instructions": vals["instructions"], "cycles": vals["cycles"],
            "wall_s": wall, "user_s": ru.ru_utime, "sys_s": ru.ru_stime}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cbench", required=True, help="cBench folder (for the inputs and __run scripts)")
    ap.add_argument("--job-dir", required=True, help="results folder of a measure.py job (with bin/ and summary.csv)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--program", default="all", help="comma-separated, or 'all' (every program in summary.csv)")
    ap.add_argument("--core", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--cycles-tolerance", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    job_dir = os.path.abspath(os.path.expanduser(a.job_dir))
    out = os.path.abspath(os.path.expanduser(a.out))
    os.makedirs(out, exist_ok=True)

    summary = read_summary(job_dir)
    progs = sorted(summary) if a.program == "all" else [x.strip() for x in a.program.split(",") if x.strip()]
    for p in progs:
        if p not in summary:
            sys.exit(f"{p} is not in {job_dir}/summary.csv")
    bins = check_binaries(job_dir, summary, progs)

    probe = subprocess.run(f"{PERF} stat -x, -e instructions:u,cycles:u -- true", shell=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if probe.returncode != 0 or parse_perf_csv(probe.stderr).get("instructions") is None:
        sys.exit("perf cannot count instructions here:\n" + probe.stderr[-500:])

    env = measure.environment("gcc")
    env["job_dir"] = job_dir
    try:
        env["perf_event_paranoid"] = open("/proc/sys/kernel/perf_event_paranoid").read().strip()
    except OSError:
        env["perf_event_paranoid"] = ""
    with open(os.path.join(out, "environment.json"), "w") as f:
        json.dump(env, f, indent=2)

    rng = random.Random(a.seed)
    raw = open(os.path.join(out, "raw.csv"), "w", newline="")
    rw = csv.writer(raw)
    rw.writerow(["program", "config", "round", "instructions", "cycles", "wall_s", "user_s", "sys_s"])
    rows, sanity = [], []
    for prog in progs:
        src = os.path.join(os.path.expanduser(a.cbench), prog, "src")
        configs = list(summary[prog])
        print(f"\n=== {prog}: {len(configs)} binaries", flush=True)
        for _ in range(a.warmup):
            for c in configs:
                measure.use_binary(src, bins[(prog, c)])
                run_once(src, a.core)
        data = {c: [] for c in configs}
        for rnd in range(1, a.rounds + 1):
            order = configs[:]
            rng.shuffle(order)
            for c in order:
                measure.use_binary(src, bins[(prog, c)])
                v = run_once(src, a.core)
                data[c].append(v)
                rw.writerow([prog, c, rnd, int(v["instructions"]), int(v["cycles"]),
                             f"{v['wall_s']:.6f}", f"{v['user_s']:.6f}", f"{v['sys_s']:.6f}"])
            raw.flush()
        med = {c: {k: statistics.median(x[k] for x in data[c]) for k in data[c][0]} for c in configs}
        spread = {c: (max(x["cycles"] for x in data[c]) - min(x["cycles"] for x in data[c])) / med[c]["cycles"]
                  for c in configs}
        base = med.get("O3")
        for c in configs:
            m = med[c]
            r = {"program": prog, "config": c, "binary_md5": summary[prog][c],
                 "instructions": int(m["instructions"]), "cycles": int(m["cycles"]),
                 "ipc": round(m["instructions"] / m["cycles"], 4),
                 "cycles_spread": round(spread[c], 4),
                 "wall_s": round(m["wall_s"], 4), "user_s": round(m["user_s"], 4), "sys_s": round(m["sys_s"], 4),
                 "cpu_share": round((m["user_s"] + m["sys_s"]) / m["wall_s"], 4)}
            if base:
                r["instr_ratio_O3_over_config"] = round(base["instructions"] / m["instructions"], 4)
                r["cycles_ratio_O3_over_config"] = round(base["cycles"] / m["cycles"], 4)
            rows.append(r)
            print(f"  {c}: {m['instructions']:.4g} instr, {m['cycles']:.4g} cycles, "
                  f"wall {m['wall_s']:.3f}s user {m['user_s']:.3f}s sys {m['sys_s']:.3f}s", flush=True)
        # binaries shared by several configurations must give the same cycles
        groups = {}
        for c in configs:
            groups.setdefault(summary[prog][c], []).append(c)
        for h, cs in groups.items():
            if len(cs) > 1:
                cyc = [med[c]["cycles"] for c in cs]
                diff = max(cyc) / min(cyc) - 1
                ok = diff <= a.cycles_tolerance
                sanity.append({"program": prog, "configs": cs, "md5": h, "cycles_diff": round(diff, 4), "ok": ok})
                print(f"  same binary {'+'.join(cs)}: cycles differ by {diff*100:.2f}% -> {'OK' if ok else 'TOO LARGE'}",
                      flush=True)
    raw.close()

    fields = list(rows[0].keys()) if rows else []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(os.path.join(out, "counts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    verdict = all(s["ok"] for s in sanity) if sanity else None
    with open(os.path.join(out, "sanity.json"), "w") as f:
        json.dump({"tolerance": a.cycles_tolerance, "pass": verdict, "groups": sanity}, f, indent=2)
    print(f"\nCYCLES_SANITY: {'PASS' if verdict else ('FAIL' if verdict is False else 'no shared binaries')}")
    print(f"COUNT_DONE: {out}")


if __name__ == "__main__":
    main()
