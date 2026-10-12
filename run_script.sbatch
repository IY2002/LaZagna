#!/bin/bash
# Run one Python script inside the container with the standard binds.
#   sbatch -A gts-<PI> --export=ALL,WORK_ROOT=<dir>,SCRIPT=/campaign/<script>.py run_script.sbatch
#SBATCH --job-name=lazagna_script
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH -q inferno
#SBATCH --time=00:30:00
#SBATCH --output=script_%j.out
#SBATCH --error=script_%j.err
set -u
module load apptainer 2>/dev/null || true
CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set}"
. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$WORK_ROOT/script"
for v in TOPK; do if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi; done
apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 "${SCRIPT:?}" "$@"
