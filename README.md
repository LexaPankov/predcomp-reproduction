# Reproducing PredComp

Reproducibility study of **"PredComp: Predicting Compiler Optimization Options with Multi-stage Learning"**,
for the **HiPEAC Student Challenge 2027** (Option B).

- **Team:** Teodora-Alexandra Pavel, Aleksei Pankov (Sapienza University of Rome)
- **Advisor:** Prof. Alessandro Mei
- **Original code:** https://github.com/LanduBing/PredComp_taco

PredComp uses machine learning to predict a sequence of GCC optimization flags for a program, aiming to beat `-O3`.
We rebuild the authors' setup from scratch, document every problem we hit, and check whether the published speed-ups hold.

## Status

| Step | Status |
|---|---|
| Environment rebuilt (Docker, Ubuntu 20.04, GCC 9.4) | ✅ Done |
| Full pipeline running on all 10 cBench programs | ✅ Done |
| Reproducibility issues documented | ✅ 18 issues, see [docs/ISSUES.md](docs/ISSUES.md) |
| First results with the authors' measurement method (laptop) | ✅ Done |
| Rigorous measurements on native Linux (department cluster, whole node, CIs) | ✅ Done, see below |
| Same sequences with a recent compiler (GCC 13.3) | ✅ Done, see below |
| Executed-instruction counts (frequency-independent check) | ✅ Done, see below |
| Exact GCC 9.2 (the paper's version) | ⬜ Optional |

## Main results

Speed-up = median time with `-O3` / median time with PredComp's sequence, measured on the DI cluster
(AMD EPYC 7301, a whole node per job) with [`scripts/measure.py`](scripts/measure.py).
"Best of Top-3" is the paper's metric: the fastest of PredComp's three predicted sequences.
Brackets: bootstrap 95% confidence interval.

![Speed-ups](results/figures/fig_speedups.png)

| Program | Paper | Ours, GCC 9.4: Top-1 | Ours, GCC 9.4: best of Top-3 | Ours, GCC 13.3: best of Top-3 |
|---|---|---|---|---|
| telecom_CRC32 | 1.424 | 1.603 | **1.604** [1.568, 1.613] | 0.785 [0.785, 0.797] |
| automotive_bitcount | 1.234 | 1.216 | **1.216** [1.204, 1.222] | **1.362** [1.349, 1.365] |
| telecom_gsm | 1.279 | 1.092 | **1.092** [1.084, 1.096] | 0.994 [0.988, 0.997] |
| network_patricia | 1.089 | 1.048 | **1.057** [1.050, 1.069] | **1.019** [1.012, 1.030] |
| network_dijkstra | 1.142 | 0.764 | **1.053** [1.045, 1.057] | **1.070** [1.063, 1.074] |
| automotive_susan_s † | 1.269 | 1.044 | **1.044** [1.044, 1.045] | **1.086** [1.086, 1.087] |
| consumer_jpeg_c † | 1.339 | 1.012 | **1.012** [1.008, 1.014] | 0.945 [0.926, 0.970] |
| security_blowfish_e | 1.023 | 0.989 | 0.989 [0.988, 0.997] | 0.996 [0.992, 1.000] |
| security_blowfish_d | 1.070* | 0.987 | 0.987 [0.987, 0.994] | 0.998 [0.997, 0.998] |
| security_sha | 1.563 | 0.963 | 0.971 [0.965, 0.974] | 0.904 [0.901, 0.909] |
| **Mean** (keeping `-O3` when nothing beats it) | **1.243** | 1.072 | **1.108** (geo 1.096) | **1.054** (geo 1.049) |

**Bold:** significantly faster than `-O3` (the whole interval is above 1).
\*For blowfish_d, the code optimizes `bf_enc.c`, but the authors' spreadsheet lists `bf_cfb64.c`.
† Re-measured with the benchmark files on the node's local disk (job 1035857); see *Measurement notes*.
Full table: [results/final_comparison.csv](results/final_comparison.csv). Every single run: `results/cluster_*/*_raw.csv`.

**What we found**

- **GCC 9.4:** the average gain over `-O3` is about **11%, against 24% in the paper**. 7 of 10 programs are significantly faster,
  but for sha and both blowfish programs all three predictions are slower than `-O3`, and susan_s and jpeg_c gain only 4% and 1%
  (the paper reports +27% and +34%). Without CRC32 the average gain is 5%.
- **The result depends a lot on the machine.** CRC32 gives 1.60× on the cluster but 1.05× on the laptop with the same compiler and flags,
  because `-O3`'s own binary is much slower on this AMD CPU. Dijkstra goes the other way (1.30× laptop, 1.05× cluster).
- **The Top-1 prediction alone is weaker** (mean 1.072, against 1.242 in the authors' own spreadsheet): for dijkstra it is 24% *slower* than `-O3`,
  and only the third sequence helps. The paper's metric needs all three candidates to be compiled and timed.
- **The Top-3 is often fewer than 3 different programs:** for CRC32 all three sequences give the same binary, for bitcount and blowfish two do.
- **With GCC 13.3** (same sequences, no retraining) the mean drops to 1.054 and the Top-1 alone is slower than `-O3` on average (0.979).
  The gain mostly disappears, except for bitcount, susan_s and dijkstra.
- No predicted sequence produced the same binary as `-O3`.

**Measurement notes.** The CPU frequency (governor, turbo) cannot be controlled on the cluster; we used a whole node, pinning,
warm-ups, interleaving and many runs instead. In the first GCC 9.4 job, susan_s and jpeg_c were very noisy and slow: both write large
output files, and the benchmarks were on the cluster's shared network disk. Re-measured on the **same node with the same binaries**
but with the files on the node's local disk (job 1035857), the noise disappears (below) and their runs are 1.0–1.7 s faster.
The table uses the re-measured values for these two; the job script now always uses the local disk.

![Noise](results/figures/fig_noise.png)

### Executed instructions (frequency-independent check)

The CPU frequency cannot be fixed on the cluster, so, as suggested by Prof. De Sensi, we also counted the
**instructions each binary executes** (`perf stat -e instructions:u`, pinned, 3 runs) with
[`scripts/count_instructions.py`](scripts/count_instructions.py). This number does not depend on the frequency.
*Instruction reduction* = instructions of `-O3` / instructions of PredComp's best Top-3 sequence (above 1 = less work).
If a speed-up came only from doing less work, the two numbers would be equal.

![Speed-up vs instruction reduction](results/figures/fig_instructions.png)

| Program | GCC 9.4: speed-up | GCC 9.4: instruction reduction | GCC 13.3: speed-up | GCC 13.3: instruction reduction |
|---|---|---|---|---|
| telecom_CRC32 | 1.604 | 0.951 | 0.785 | 1.000 |
| automotive_bitcount | 1.216 | 1.223 | 1.362 | 1.217 |
| telecom_gsm | 1.092 | 1.111 | 0.994 | 0.992 |
| network_patricia | 1.057 | 1.024 | 1.019 | 0.961 |
| network_dijkstra | 1.053 | 1.069 | 1.070 | 1.014 |
| automotive_susan_s | 1.044 | 1.221 | 1.086 | 1.230 |
| consumer_jpeg_c | 1.012 | 1.006 | 0.945 | 0.930 |
| security_blowfish_e | 0.989 | 0.988 | 0.996 | 0.979 |
| security_blowfish_d | 0.987 | 0.991 | 0.998 | 0.982 |
| security_sha | 0.971 | 0.923 | 0.904 | 0.890 |

- **Most gains match the reduction in instructions:** with GCC 9.4, for 7 of 10 programs the speed-up and the instruction reduction agree within about 3%.
  This is consistent with (but does not prove) the gain coming from executing less code, and it does not depend on the CPU frequency.
- **CRC32 is the exception:** with GCC 9.4 PredComp's binary executes 5% *more* instructions than `-O3` but is 1.60× faster.
  So the gain cannot come from fewer instructions but from how efficiently this CPU runs the code, consistent with it shrinking to 1.05× on the laptop.
  With GCC 13.3 the two binaries execute the same number of instructions, but PredComp's is 21% slower.
- **susan_s:** 22% fewer instructions, but only 4% (GCC 9.4) and 9% (GCC 13.3) faster. Fewer instructions ≠ proportionally faster.
- **dijkstra's Top-1** executes 8% (GCC 9.4) and 14% (GCC 13.3) more instructions than `-O3`, which explains why it is slower.
- Counts are highly repeatable: binaries with the same MD5 have the same count to within 0.0001%. For GCC 9.4 the MD5s match the binaries timed above.
- Cycles are also in the CSVs but we do **not** use them: the two jobs ran on the same core at the same time, which distorts cycles (not instructions).

Data: [results/instruction_counts_vs_speedup.csv](results/instruction_counts_vs_speedup.csv), `results/instructions_*/instructions.csv`.

### First results on a laptop (authors' measurement method)

WSL2, Docker with Ubuntu 20.04 and GCC 9.4, the authors' own timing (pinned to core 0, 3 runs, no warm-up, mean only):
mean speed-up **1.106** (geometric 1.101) vs the paper's 1.243. Data: [results/wsl_docker_gcc9.4_authors_method.csv](results/wsl_docker_gcc9.4_authors_method.csv).

## How to reproduce

You need Linux (or WSL2) with Docker and git.

**1. Get this repository and the original code** (side by side):
```bash
git clone https://github.com/LexaPankov/predcomp-reproduction.git
git clone https://github.com/LanduBing/PredComp_taco.git
```

**2. Apply our code fixes** (renames `PredComp_taco` to `PredComp`, see [docs/ISSUES.md](docs/ISSUES.md)):
```bash
bash predcomp-reproduction/scripts/apply_patches.sh
```

**3. Build the environment** (10–20 minutes):
```bash
sudo docker build -t predcomp:focal predcomp-reproduction/docker
```

**4. Run PredComp** (predicts the Top-3 sequences and times them the authors' way). `--privileged` is needed so `perf` works inside the container:
```bash
sudo docker run --rm -it --privileged -v "$PWD/PredComp":/work/PredComp predcomp:focal bash
python main_test.py --bin_path /usr/bin 2>&1 | tee test_run.log   # 1 program, a few minutes
python main.py      --bin_path /usr/bin 2>&1 | tee full_run.log   # all 10 programs, 20-40 minutes
```
Files created inside the container belong to root. After `exit`, run `sudo chown -R $USER PredComp`.

**5. Measure rigorously** with the sequences from those logs (see below).

## Rigorous measurements

`scripts/measure.py` re-times PredComp's Top-3 sequences against `-O3`, following
Prof. De Sensi's advice and Hoefler & Belli (SC'15):

- the authors' own build commands, and every output checked against `-O3` before timing;
- 5 warm-up runs per configuration, not counted;
- measured runs **interleaved in a new random order every round**, so machine drift hits all configurations equally;
- every single time saved (`*_raw.csv`);
- runs continue until the 95% CI of the median is within 1% (10 to 50 rounds);
- mean, median, standard deviation, 95% CIs, and the speed-up over `-O3` with a bootstrap 95% CI (`summary.csv`);
- the MD5 of each binary, to spot sequences that produce the same program.

It only needs Python's standard library, so it runs inside the Docker image (GCC 9.4) and directly on a node (GCC 13.3).
On the department cluster (SLURM), with a whole node per job (`--exclusive`) and the benchmarks copied to the node's local disk:

```bash
cd ~/predcomp-reproduction          # logs of main.py runs in ~/logs/
sbatch scripts/cluster_measure.sh gcc9     # Ubuntu 20.04 container, GCC 9.4
sbatch scripts/cluster_measure.sh gcc13    # node's own GCC 13.3
sbatch scripts/cluster_measure.sh gcc9 --program automotive_susan_s,consumer_jpeg_c   # only some programs
sbatch scripts/cluster_instructions.sh gcc9    # executed-instruction counts (1 hour max)
sbatch scripts/cluster_instructions.sh gcc13
```

## Repository layout

```
docker/Dockerfile           environment with all dependency fixes
scripts/apply_patches.sh    fixes to the original code
scripts/measure.py          rigorous timing (warm-ups, interleaving, CIs, binary check)
scripts/cluster_measure.sh  SLURM job for the cluster
scripts/count_instructions.py     executed-instruction counts with perf stat
scripts/cluster_instructions.sh   SLURM job for the instruction counts
docs/ISSUES.md              the 18 reproducibility issues
results/final_comparison.csv  paper vs laptop vs cluster (GCC 9.4 and 13.3)
results/cluster_*/          every measurement of the three cluster jobs
results/instructions_*/     instruction counts (GCC 9.4 and 13.3)
results/figures/            the figures above
```
