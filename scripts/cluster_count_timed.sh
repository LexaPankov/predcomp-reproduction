#!/bin/bash
# Count instructions and cycles of the exact binaries timed by measure.py, on a whole node.
# Runs GCC 9.4 (inside our Ubuntu 20.04 container) and then GCC 13.3 (on the host), one after
# the other, on the same core, with everything on the node's local disk.
# Submit from ~/predcomp-reproduction:
#
#   sbatch scripts/cluster_count_timed.sh                       # full run, both compilers
#   sbatch -t 00:15:00 scripts/cluster_count_timed.sh --program telecom_CRC32 --rounds 2   # smoke test
#
# The timed binaries are in the folders of the timing jobs (override with GCC9_JOB / GCC13_JOB):
#   GCC9_JOB=$HOME/backup_results/cluster_gcc9_job1035047
#   GCC13_JOB=$HOME/backup_results/cluster_gcc13_job1035048
#
#SBATCH --job-name=timedcount
#SBATCH --partition=thesis
#SBATCH --time=02:00:00
#SBATCH --exclusive
#SBATCH --output=%x_%j.log

set -e
REPO=$HOME/predcomp-reproduction
GCC9_JOB=${GCC9_JOB:-$HOME/backup_results/cluster_gcc9_job1035047}
GCC13_JOB=${GCC13_JOB:-$HOME/backup_results/cluster_gcc13_job1035048}
WORK=/tmp/${USER}_timedcount_${SLURM_JOB_ID}
trap 'rm -rf "$WORK"' EXIT

echo "node: $(hostname)  job: $SLURM_JOB_ID  perf_event_paranoid: $(cat /proc/sys/kernel/perf_event_paranoid)"
for J in "$GCC9_JOB" "$GCC13_JOB"; do
    [ -f "$J/summary.csv" ] && [ -d "$J/bin" ] || { echo "missing summary.csv or bin/ in $J"; exit 1; }
done
rm -rf "$WORK" && mkdir -p "$WORK"
cp -r $HOME/PredComp/Dataset/cBench_V1.1 "$WORK/cbench"

# ---- GCC 9.4 binaries, inside the container (they need Ubuntu 20.04's libraries)
mkdir -p "$WORK/job9" && cp -r "$GCC9_JOB/bin" "$GCC9_JOB/summary.csv" "$WORK/job9/"
OUT9=results/timed_counts_gcc9_job${SLURM_JOB_ID}
mkdir -p $REPO/$OUT9
docker image inspect predcomp:focal >/dev/null 2>&1 || docker load -i $HOME/predcomp_focal.tar
docker run --rm --privileged --user "$(id -u):$(id -g)" -e SLURM_JOB_ID \
    -v "$WORK":/work/w -v $REPO:/work/repo predcomp:focal \
    bash -c 'export PERF=$(ls /usr/lib/linux-tools/*/perf | head -1); echo "perf: $PERF"; exec python /work/repo/scripts/count_timed_binaries.py "$@"' _ \
        --cbench /work/w/cbench --job-dir /work/w/job9 --out /work/repo/$OUT9 "$@"

# ---- GCC 13.3 binaries, on the host
mkdir -p "$WORK/job13" && cp -r "$GCC13_JOB/bin" "$GCC13_JOB/summary.csv" "$WORK/job13/"
OUT13=results/timed_counts_gcc13_job${SLURM_JOB_ID}
python3 $REPO/scripts/count_timed_binaries.py --cbench "$WORK/cbench" --job-dir "$WORK/job13" --out $REPO/$OUT13 "$@"

echo "TIMEDCOUNT_JOB_DONE: $OUT9 $OUT13"
