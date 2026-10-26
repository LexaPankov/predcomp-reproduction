#!/usr/bin/env python3
"""
Rigorous timing of PredComp's flag sequences against -O3 on cBench.

Follows the advice of Prof. De Sensi and Hoefler & Belli (SC'15, "Scientific
Benchmarking of Parallel Computing Systems"):
  * the same build and run commands as the authors (Dataset/process/heads.py),
    so only the measurement method changes;
  * every output is checked against the -O3 output before timing;
  * W warm-up runs per configuration, not counted;
  * measured runs are INTERLEAVED in a new random order every round, so slow
    drifts of the machine (other jobs, temperature) hit all configurations equally;
  * every single time is saved (raw CSV), nothing is averaged away;
  * runs continue until the 95% confidence interval of the median is within
    --target of the median for every configuration (or --max-rounds is reached);
  * the summary reports mean, median, standard deviation, 95% CIs and the
    speed-up over -O3 with a bootstrap 95% CI.

Only the Python standard library is needed, so it runs both inside our Docker
image (GCC 9.4) and directly on a cluster node (e.g. GCC 13).

Examples
  # PredComp's top-3 sequences, read from the log of a main.py run:
  python3 measure.py --cbench ~/PredComp/Dataset/cBench_V1.1 \
      --program telecom_CRC32 --from-log full_run.log --out results/crc32_gcc9

  # every program found in the log, one after the other:
  python3 measure.py --cbench ... --program all --from-log full_run.log --out results/gcc9

  # your own flags:
  python3 measure.py --cbench ... --program automotive_bitcount \
      --flags "-O3 -funroll-loops" --out results/test
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time

# ---------------------------------------------------------------- the authors' settings
# (source file that PredComp optimises, compile flags, link flags), from cbench.json
PROGRAMS = {
    "automotive_bitcount": ("bitcnts.c", "-c", "-lm"),
    "telecom_gsm": ("short_term.c", "-c -DSASR -DSTUPID_COMPILER -DNeedFunctionPrototypes=1", "-lm"),
    "network_dijkstra": ("dijkstra_large.c", "-c", "-lm"),
    "security_sha": ("sha.c", "-c", "-lm"),
    "security_blowfish_d": ("bf_enc.c", "-c", "-lm"),
    "security_blowfish_e": ("bf_enc.c", "-c", "-lm"),
    "consumer_jpeg_c": ("jcphuff.c", "-c", "-lm"),
    "automotive_susan_s": ("susan.c", "-c", "-lm"),
    "network_patricia": ("patricia.c", "-c", "-lm"),
    "telecom_CRC32": ("crc_32.c", "-c", "-lm"),
}
# the authors skip the output check for these two (their output is not deterministic)
NO_OUTPUT_CHECK = {"security_sha", "office_rsynth"}

# two-sided 95% Student t quantiles, df = 1..30
T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
       2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
       2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def sh(cmd, cwd):
    return subprocess.run(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# ---------------------------------------------------------------- statistics
def t95(n):
    return T95[n - 2] if 2 <= n <= 31 else 1.96


def mean_ci(xs):
    n = len(xs)
    m = statistics.fmean(xs)
    if n < 2:
        return m, m, m
    h = t95(n) * statistics.stdev(xs) / math.sqrt(n)
    return m, m - h, m + h


def median_ci(xs):
    """Non-parametric 95% CI of the median (Le Boudec), as recommended by Hoefler & Belli."""
    s = sorted(xs)
    n = len(s)
    med = statistics.median(s)
    if n < 6:
        return med, s[0], s[-1]
    lo = math.floor((n - 1.96 * math.sqrt(n)) / 2)          # 1-based rank
    hi = math.ceil(1 + (n + 1.96 * math.sqrt(n)) / 2)
    lo, hi = max(lo, 1), min(hi, n)
    return med, s[lo - 1], s[hi - 1]


def speedup_ci(base, other, reps=2000, seed=1):
    """Speed-up = median(-O3) / median(config), with a bootstrap 95% CI."""
    rng = random.Random(seed)
    point = statistics.median(base) / statistics.median(other)
    boots = []
    for _ in range(reps):
        b = [rng.choice(base) for _ in base]
        o = [rng.choice(other) for _ in other]
        boots.append(statistics.median(b) / statistics.median(o))
    boots.sort()
    return point, boots[int(0.025 * reps)], boots[int(0.975 * reps) - 1]


# ---------------------------------------------------------------- build, check, time
def build(src, cc, flags, prog):
    """Exactly the authors' commands (with the -lm order fixed, our Issue 18)."""
    file, cmp, ld = PROGRAMS[prog]
    cmd = f"make clean >/dev/null; {cc} -O3 {cmp} *.c"
    if flags.strip() != "-O3":
        cmd += f" && {cc} -O3 {flags} {cmp} {file}"
    cmd += f" && {cc} *.o -o a.out {ld}"
    return sh(cmd, src)


def run_once(src, core, timer):
    """One execution of the benchmark; returns elapsed seconds."""
    if timer == "perf":   # the authors' method: perf's 'seconds time elapsed'
        p = sh(f"taskset -c {core} perf stat -- ./__run 1 >/dev/null", src)
        m = re.search(r"([\d.,]+)\s+seconds time elapsed", p.stderr)
        if p.returncode != 0 or not m:
            raise RuntimeError(p.stderr[-500:])
        return float(m.group(1).replace(",", "."))
    t0 = time.perf_counter()
    p = subprocess.run(["taskset", "-c", str(core), "./__run", "1"], cwd=src,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    t1 = time.perf_counter()
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-500:])
    return t1 - t0


def use_binary(src, binpath):
    """Point a.out (the name __run executes) at this configuration's binary."""
    target = os.path.join(src, "a.out")
    if os.path.lexists(target):
        os.remove(target)
    os.symlink(os.path.abspath(binpath), target)


# ---------------------------------------------------------------- inputs
def read_log(path):
    """{program: [top-1, top-2, top-3]} from the output of the authors' main.py."""
    seqs = {}
    pat = re.compile(r"^(\S+) Top-(\d+) sequence: (.*), exec time:")
    with open(path, errors="replace") as f:
        for line in f:
            m = pat.match(line.strip())
            if m:
                seqs.setdefault(m.group(1), {})[int(m.group(2))] = m.group(3).strip()
    return {p: [d[k] for k in sorted(d)] for p, d in seqs.items()}


def environment(cc):
    def first(cmd):
        try:
            return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True).stdout.strip().splitlines()[0]
        except Exception:
            return ""
    return {
        "host": socket.gethostname(),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kernel": platform.release(),
        "compiler": first(f"{cc} --version"),
        "cpu": first("lscpu | grep 'Model name' | sed 's/Model name: *//'"),
        "slurm_job": os.environ.get("SLURM_JOB_ID", ""),
        "python": platform.python_version(),
        "command": " ".join(sys.argv),
    }


# ---------------------------------------------------------------- one program
def measure_program(prog, configs, a, out_dir):
    src = os.path.join(os.path.expanduser(a.cbench), prog, "src")
    if not os.path.isdir(src):
        sys.exit(f"not found: {src}")
    bins = os.path.join(out_dir, "bin", prog)
    os.makedirs(bins, exist_ok=True)
    print(f"\n=== {prog}: {len(configs)} configurations, compiler: {a.cc}", flush=True)

    # 1. build every configuration once, keep its binary
    ok = {}
    status = {}
    hashes = {}
    for label, flags in configs.items():
        if os.path.lexists(os.path.join(src, "a.out")):
            os.remove(os.path.join(src, "a.out"))
        p = build(src, a.cc, flags, prog)
        if p.returncode != 0:
            status[label] = "compile_error: " + p.stderr.strip().splitlines()[-1][:200] if p.stderr.strip() else "compile_error"
            print(f"  {label}: COMPILE ERROR, skipped", flush=True)
            continue
        dst = os.path.join(bins, f"{label}.out")
        shutil.copy2(os.path.join(src, "a.out"), dst)
        ok[label] = dst
        status[label] = "ok"
        hashes[label] = md5(dst)
        print(f"  {label}: built ({md5(dst)[:8]})", flush=True)
    if "O3" not in ok:
        print("  -O3 did not build, skipping this program", flush=True)
        return None

    # 2. reference output from -O3, then every other configuration must match it
    use_binary(src, ok["O3"])
    sh("./_ccc_check_output.clean", src)
    run_once(src, a.core, a.timer)
    sh("./_ccc_check_output.copy", src)
    for label in list(ok):
        if label == "O3":
            continue
        use_binary(src, ok[label])
        try:
            run_once(src, a.core, a.timer)
        except RuntimeError as e:
            status[label] = "run_error"
            del ok[label]
            print(f"  {label}: RUN ERROR, skipped ({str(e)[:120]})", flush=True)
            continue
        diff = sh("./_ccc_check_output.diff; cat tmp-ccc-diff", src).stdout.strip()
        if diff and prog not in NO_OUTPUT_CHECK:
            status[label] = "wrong_output"
            del ok[label]
            print(f"  {label}: WRONG OUTPUT, skipped", flush=True)

    # 3. warm-up, not recorded
    labels = list(ok)
    for _ in range(a.warmup):
        for label in labels:
            use_binary(src, ok[label])
            run_once(src, a.core, a.timer)
    print(f"  warm-up done ({a.warmup} runs each)", flush=True)

    # 4. interleaved measured rounds until every CI is narrow enough
    raw_path = os.path.join(out_dir, f"{prog}_raw.csv")
    times = {l: [] for l in labels}
    rng = random.Random(a.seed)
    with open(raw_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["program", "config", "round", "position", "seconds", "unix_time"])
        rnd = 0
        while rnd < a.max_rounds:
            rnd += 1
            order = labels[:]
            rng.shuffle(order)
            for pos, label in enumerate(order):
                use_binary(src, ok[label])
                s = run_once(src, a.core, a.timer)
                times[label].append(s)
                w.writerow([prog, label, rnd, pos, f"{s:.6f}", f"{time.time():.3f}"])
            f.flush()
            if rnd >= a.min_rounds:
                widths = []
                for label in labels:
                    med, lo, hi = median_ci(times[label])
                    widths.append(max(med - lo, hi - med) / med)
                if max(widths) <= a.target:
                    break
            if rnd % 10 == 0:
                print(f"  round {rnd}", flush=True)
    use_binary(src, ok["O3"])
    print(f"  {rnd} rounds measured", flush=True)

    # 5. summary
    rows = []
    for label in configs:
        r = {"program": prog, "config": label, "flags": configs[label], "status": status.get(label, ""),
             "binary_md5": hashes.get(label, ""),
             # same binary as -O3: the flags changed nothing, so any measured difference is pure noise
             "same_binary_as_O3": (hashes.get(label) == hashes.get("O3")) if label in hashes else ""}
        if label in times and times[label]:
            xs = times[label]
            m, mlo, mhi = mean_ci(xs)
            med, dlo, dhi = median_ci(xs)
            r.update(n=len(xs), mean=m, mean_ci_low=mlo, mean_ci_high=mhi,
                     median=med, median_ci_low=dlo, median_ci_high=dhi,
                     stdev=statistics.stdev(xs) if len(xs) > 1 else 0.0,
                     min=min(xs), max=max(xs))
            sp, slo, shi = speedup_ci(times["O3"], xs, seed=a.seed)
            r.update(speedup_vs_O3=sp, speedup_ci_low=slo, speedup_ci_high=shi)
        rows.append(r)
    return rows


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cbench", required=True, help="path to Dataset/cBench_V1.1")
    ap.add_argument("--program", required=True, help="cBench program name, or 'all' (with --from-log)")
    ap.add_argument("--from-log", action="append", default=[],
                    help="log of the authors' main.py: use its Top-k sequences (repeatable)")
    ap.add_argument("--flags", action="append", default=[], help="extra flag sequence (repeatable)")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--cc", default="gcc", help="compiler (default: gcc on PATH)")
    ap.add_argument("--core", type=int, default=2, help="CPU core to pin to (default 2: core 0 handles most OS interrupts)")
    ap.add_argument("--timer", choices=["wall", "perf"], default="wall",
                    help="wall: Python's clock around __run (no perf needed); perf: the authors' 'perf stat'")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--min-rounds", type=int, default=10)
    ap.add_argument("--max-rounds", type=int, default=50)
    ap.add_argument("--target", type=float, default=0.01, help="max relative half-width of the median CI (default 1%%)")
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    a.out = os.path.abspath(os.path.expanduser(a.out))

    from_log = {}
    for path in a.from_log:
        from_log.update(read_log(os.path.expanduser(path)))
    progs = sorted(from_log) if a.program == "all" else [a.program]
    for p in progs:
        if p not in PROGRAMS:
            sys.exit(f"unknown program {p}; known: {', '.join(PROGRAMS)}")

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "environment.json"), "w") as f:
        json.dump(environment(a.cc), f, indent=2)

    all_rows = []
    for p in progs:
        configs = {"O3": "-O3"}
        for i, s in enumerate(from_log.get(p, []), 1):
            configs[f"top{i}"] = s
        for i, s in enumerate(a.flags, 1):
            configs[f"custom{i}"] = s
        if len(configs) == 1:
            print(f"warning: only -O3 for {p} (no --from-log entry or --flags)")
        rows = measure_program(p, configs, a, a.out)
        if rows:
            all_rows += rows
            for r in rows:
                if "median" in r:
                    same = "  (same binary as -O3)" if r["same_binary_as_O3"] is True and r["config"] != "O3" else ""
                    print(f"  {r['config']:8s} median {r['median']:.4f}s "
                          f"[{r['median_ci_low']:.4f}, {r['median_ci_high']:.4f}]  "
                          f"speed-up {r['speedup_vs_O3']:.3f} [{r['speedup_ci_low']:.3f}, {r['speedup_ci_high']:.3f}]  n={r['n']}{same}")
                else:
                    print(f"  {r['config']:8s} {r['status']}")

    cols = ["program", "config", "status", "n", "mean", "mean_ci_low", "mean_ci_high", "median",
            "median_ci_low", "median_ci_high", "stdev", "min", "max",
            "speedup_vs_O3", "speedup_ci_low", "speedup_ci_high", "same_binary_as_O3", "binary_md5", "flags"]
    with open(os.path.join(a.out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})
    print(f"\nsaved: {a.out}/summary.csv, {a.out}/*_raw.csv, {a.out}/environment.json")


if __name__ == "__main__":
    main()
