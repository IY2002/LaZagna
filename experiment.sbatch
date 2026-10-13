#!/bin/bash
# Fixed-configuration experiments (campaign/experiment.py), one task-file line per array task.
#   sbatch -A gts-<PI> --array=0-<N-1>%<max> --export=ALL,WORK_ROOT=<dir>,TASKS=<file> experiment.sbatch
# Run from the repo root. TASKS must live under WORK_ROOT (read inside the container as
# /work/...); by convention task lists live in $WORK_ROOT/tasks/.
# Layout: logs -> logs/exp/, per-task work dirs -> $WORK_ROOT/runs/<job>/task_<n>/,
#         results -> $WORK_ROOT/results/<task id>.json
#SBATCH --job-name=lazagna_exp
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH -q inferno
#SBATCH --time=12:00:00
#SBATCH --output=logs/exp/exp_%A_%a.out
#SBATCH --error=logs/exp/exp_%A_%a.err
set -u
module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }
CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set}"
TASKS="${TASKS:?TASKS not set}"
. "$CAMPAIGN/campaign/binds.sh"
# Per-task work dir: $WORK_ROOT/runs/<array job>/task_<index> (results go to $WORK_ROOT/results).
RUN_DIR="$WORK_ROOT/runs/${SLURM_ARRAY_JOB_ID}/task_${SLURM_ARRAY_TASK_ID}"
lazagna_binds "$RUN_DIR"
export APPTAINERENV_TASKS="/work/${TASKS#$WORK_ROOT/}"
export APPTAINERENV_TASK_INDEX="${SLURM_ARRAY_TASK_ID}"
for v in TALL CW FORCE; do
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
echo "EXP task ${SLURM_ARRAY_TASK_ID} START $(date -Is)"
apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/experiment.py
rc=$?
# Per-task RRGs are multi-GB and only useful within the task.
rm -rf "$RUN_DIR"/{base_rrg,rrg_3d}
echo "EXP task ${SLURM_ARRAY_TASK_ID} DONE rc=$rc $(date -Is)"
exit $rc
