#!/bin/bash
# Rigorous measurements on the DI cluster (SLURM). Submit from ~/predcomp-reproduction:
#
#   sbatch scripts/cluster_measure.sh gcc9    # inside our Docker image: Ubuntu 20.04, GCC 9.4 (like the paper)
#   sbatch scripts/cluster_measure.sh gcc13   # directly on the node: Ubuntu 24.04, GCC 13.3 (recent GCC)
#
# The two can run at the same time: each job works on its own copy of cBench.
# Only some programs:  sbatch scripts/cluster_measure.sh gcc9 --program automotive_susan_s,consumer_jpeg_c
#
# Needs, in your home folder:
#   ~/PredComp                  the authors' code, after scripts/apply_patches.sh
#   ~/predcomp-reproduction     this repository
#   ~/predcomp_focal.tar        the Docker image (from 'docker save'), for gcc9
#   ~/logs/*.log                logs of main.py runs, which contain the Top-3 sequences
#
#SBATCH --job-name=measure
#SBATCH --partition=thesis
#SBATCH --time=08:00:00
#SBATCH --exclusive
#SBATCH --output=%x_%j.log

set -e
MODE=${1:-gcc9}
shift || true                           # anything after the mode goes to measure.py, e.g. --max-rounds 30
REPO=$HOME/predcomp-reproduction
NAME=cluster_${MODE}_job${SLURM_JOB_ID}
# private copy of cBench on the node's LOCAL disk: no network-filesystem I/O during timing,
# and two jobs never share a copy. Results are still written to the home folder.
WORK=/tmp/${USER}_cbench_${MODE}_${SLURM_JOB_ID}
trap 'rm -rf "$WORK"' EXIT

echo "node: $(hostname)  mode: $MODE  job: $SLURM_JOB_ID"
ls $HOME/logs/*.log >/dev/null           # stop early if there are no logs
rm -rf "$WORK" && cp -a $HOME/PredComp/Dataset/cBench_V1.1 "$WORK"
mkdir -p $REPO/results/$NAME

if [ "$MODE" = "gcc9" ]; then
    # the image was built on another node: load it here if needed
    docker image inspect predcomp:focal >/dev/null 2>&1 || docker load -i $HOME/predcomp_focal.tar
    # --user: files written to the home folder stay ours
    # no --privileged: measure.py times with Python's clock, so perf is not needed
    docker run --rm --user "$(id -u):$(id -g)" -e SLURM_JOB_ID \
        -v "$WORK":/work/cbench -v $REPO:/work/repo -v $HOME/logs:/work/logs \
        predcomp:focal \
        python /work/repo/scripts/measure.py --cbench /work/cbench --program all \
            $(ls $HOME/logs/*.log | sed 's|.*/|--from-log /work/logs/|' | tr '\n' ' ') \
            --out /work/repo/results/$NAME "$@"
elif [ "$MODE" = "gcc13" ]; then
    python3 $REPO/scripts/measure.py --cbench "$WORK" --program all \
        $(ls $HOME/logs/*.log | sed 's|^|--from-log |' | tr '\n' ' ') \
        --out $REPO/results/$NAME "$@"
else
    echo "unknown mode: $MODE (use gcc9 or gcc13)"; exit 1
fi
echo "MEASURE_DONE: results in $REPO/results/$NAME"
