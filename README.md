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
| Environment rebuilt (Docker, Ubuntu 20.04) | ✅ Done |
| Full pipeline running on all 10 cBench programs | ✅ Done |
| Reproducibility issues documented | ✅ 18 issues, see [docs/ISSUES.md](docs/ISSUES.md) |
| First results with the authors' measurement method | ✅ Done, see below |
| Rigorous measurements on native Linux (warm-ups, many runs, fixed CPU frequency) | 🔄 In progress |
| GCC 9.2 (paper's version) and a recent GCC | 🔄 Planned |

## First results

Speed-up = time with `-O3` / time with PredComp's best predicted flags (Top-3).
Authors' numbers: "Comb, Top-3" from their `predcomp_result.xlsx`.

| Program | Ours | Authors' |
|---|---|---|
| network_dijkstra | **1.298** | 1.142 |
| telecom_gsm | 1.270 | 1.279 |
| automotive_susan_s | 1.190 | 1.269 |
| network_patricia | **1.124** | 1.089 |
| automotive_bitcount | 1.090 | 1.234 |
| telecom_CRC32 | 1.045 | 1.424 |
| security_blowfish_e | **1.039** | 1.023 |
| security_sha | 1.000 | 1.563 |
| consumer_jpeg_c | 1.000 | 1.339 |
| security_blowfish_d | 1.000 | 1.070* |
| **Arithmetic mean** | **1.106** | **1.243** |
| **Geometric mean** | **1.101** | **1.233** |

**Bold:** we matched or beat the authors. **1.000:** none of the 3 predictions beat `-O3`, so `-O3` was kept.
\*For blowfish_d, the code optimizes `bf_enc.c`, but the authors' spreadsheet lists `bf_cfb64.c`, so this pair is not directly comparable.

**How these were measured:** WSL2 on a laptop, Docker with Ubuntu 20.04 and GCC 9.4.0 (the paper used 9.2.0),
using the authors' own method: pinned to core 0, 3 runs, no warm-up, mean only.
These numbers are **preliminary**. The direction of the paper's claim holds, but the average gain is about half.
Raw data: [results/wsl_docker_gcc9.4_authors_method.csv](results/wsl_docker_gcc9.4_authors_method.csv).

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

**4. Run.** `--privileged` is needed so `perf` can measure time inside the container:
```bash
sudo docker run --rm -it --privileged -v "$PWD/PredComp":/work/PredComp predcomp:focal bash
python main_test.py --bin_path /usr/bin 2>&1 | tee test_run.log   # 1 program, a few minutes
python main.py      --bin_path /usr/bin 2>&1 | tee full_run.log   # all 10 programs, 20-40 minutes
```

Files created inside the container belong to root. After `exit`, run `sudo chown -R $USER PredComp`.

## Rigorous measurements (in progress)

`scripts/measure.py` re-times PredComp's Top-3 sequences against `-O3`, following
Prof. De Sensi's advice and Hoefler & Belli (SC'15):

- the authors' own build commands, and every output checked against `-O3` before timing;
- 5 warm-up runs per configuration, not counted;
- measured runs **interleaved in a new random order every round**, so machine drift hits all configurations equally;
- every single time saved (`*_raw.csv`);
- runs continue until the 95% CI of the median is within 1% (10 to 50 rounds);
- mean, median, standard deviation, 95% CIs, and the speed-up over `-O3` with a bootstrap 95% CI (`summary.csv`);
- the MD5 of each binary: if a sequence produces **the same binary as `-O3`**, any measured difference is pure noise.

It only needs Python's standard library, so it runs inside the Docker image (GCC 9.4) and directly on a node (GCC 13.3).
On the department cluster (SLURM), with a whole node per job (`--exclusive`):

```bash
cd ~/predcomp-reproduction
sbatch scripts/cluster_measure.sh gcc9     # Ubuntu 20.04 container, GCC 9.4
sbatch scripts/cluster_measure.sh gcc13    # node's own GCC 13.3
```

## Repository layout

```
docker/Dockerfile          environment with all dependency fixes
scripts/apply_patches.sh   fixes to the original code
scripts/measure.py         rigorous timing (warm-ups, interleaving, CIs)
scripts/cluster_measure.sh SLURM job for the cluster
docs/ISSUES.md             the 18 reproducibility issues
results/                   measured data
```

## Next steps

Following advice from Prof. Daniele De Sensi (and Hoefler & Belli, *Scientific Benchmarking of Parallel Computing Systems*, SC'15):

- 5–10 warm-up runs, then enough measured runs for a small confidence interval
- report mean and median, with the full distribution
- native Linux, with the `performance` CPU governor and turbo boost off
- GCC 9.2 to match the paper, plus a recent GCC as an extension
