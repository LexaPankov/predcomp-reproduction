#!/bin/bash
# Count executed instructions on the DI cluster (SLURM). Submit from ~/predcomp-reproduction:
#
#   sbatch scripts/cluster_instructions.sh gcc9    # inside our Docker image (GCC 9.4); needs --privileged for perf
#   sbatch scripts/cluster_instructions.sh gcc13   # directly on the node (GCC 13.3)
#
# Instruction counts do not depend on the CPU frequency or on other jobs, so no
# exclusive node is needed and the job is short.
#
#SBATCH --job-name=instr
#SBATCH --partition=thesis
#SBATCH --time=01:00:00
#SBATCH --output=%x_%j.log

set -e
MODE=${1:-gcc9}
shift || true
REPO=$HOME/predcomp-reproduction
NAME=instructions_${MODE}_job${SLURM_JOB_ID}
WORK=/tmp/${USER}_cbench_instr_${MODE}_${SLURM_JOB_ID}
trap 'rm -rf "$WORK"' EXIT

echo "node: $(hostname)  mode: $MODE  job: $SLURM_JOB_ID"
ls $HOME/logs/*.log >/dev/null
rm -rf "$WORK" && cp -r $HOME/PredComp/Dataset/cBench_V1.1 "$WORK"
mkdir -p $REPO/results/$NAME

if [ "$MODE" = "gcc9" ]; then
    docker image inspect predcomp:focal >/dev/null 2>&1 || docker load -i $HOME/predcomp_focal.tar
    # perf needs --privileged inside a container; /usr/bin/perf there refuses the host's newer kernel,
    # so we call the real perf binary from linux-tools directly (PERF)
    docker run --rm --privileged --user "$(id -u):$(id -g)" -e SLURM_JOB_ID \
        -v "$WORK":/work/cbench -v $REPO:/work/repo -v $HOME/logs:/work/logs \
        predcomp:focal \
        bash -c 'export PERF=$(ls /usr/lib/linux-tools/*/perf | head -1); echo "perf: $PERF"; exec python /work/repo/scripts/count_instructions.py "$@"' _ \
            --cbench /work/cbench --program all \
            $(ls $HOME/logs/*.log | sed 's|.*/|--from-log /work/logs/|' | tr '\n' ' ') \
            --out /work/repo/results/$NAME "$@"
elif [ "$MODE" = "gcc13" ]; then
    python3 $REPO/scripts/count_instructions.py --cbench "$WORK" --program all \
        $(ls $HOME/logs/*.log | sed 's|^|--from-log |' | tr '\n' ' ') \
        --out $REPO/results/$NAME "$@"
else
    echo "unknown mode: $MODE (use gcc9 or gcc13)"; exit 1
fi
echo "INSTR_JOB_DONE: results in $REPO/results/$NAME"
