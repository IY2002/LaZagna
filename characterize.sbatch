#!/bin/bash
# ============================================================================
# Benchmark characterization: synthesis + pack only, one design per array task.
# Each task fills the shared synthesis/pack cache (campaign_work/prep_cache), so the
# studies that follow never re-synthesize. Then a summary job prints the table:
# measured block demand, the 2D device sized to it, the matching 3D device, utilization.
#
#   CHARACTERIZE=1 bash submit_campaign.sh          (submits the array + summary)
#
# Yosys is the memory driver for the large Koios designs, hence 64G per task.
# ============================================================================
#SBATCH --job-name=lazagna_char
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH -q inferno
#SBATCH --time=08:00:00
#SBATCH --output=characterize_%A_%a.out
#SBATCH --error=characterize_%A_%a.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:-$CAMPAIGN/campaign_work/characterize}"
W="$WORK_ROOT/char_${SLURM_ARRAY_TASK_ID:-0}"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$W"

for v in CHAR_DESIGNS TARGET_UTIL TALL; do
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
ARGS=()
if [ -n "${SUMMARIZE:-}" ]; then
  ARGS=(--summarize)
else
  export APPTAINERENV_CHAR_INDEX="${SLURM_ARRAY_TASK_ID:-0}"
fi

apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/characterize.py "${ARGS[@]}"
echo "CHARACTERIZE DONE $(date -Is)"
