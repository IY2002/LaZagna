#!/bin/bash
# ============================================================================
# LaZagna campaign COLLECT job — runs after the worker array + extras finish
# (afterany, so a partial campaign still gets summarized). Walks every job's
# tasks_run under WORK_ROOT + the optuna journals, writes campaign_summary.md.
# ============================================================================
#SBATCH --job-name=lazagna_collect
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH -q inferno
#SBATCH --time=01:00:00
#SBATCH --output=collect_%j.out
#SBATCH --error=collect_%j.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"
[ -f "$WORK_ROOT/campaign.env" ] && . "$WORK_ROOT/campaign.env"

if ! apptainer exec --no-home --cleanenv "$SIF" test -d /opt/LaZagna/base_rrg; then
  echo "FATAL: lazagna.sif is STALE. rm lazagna.sif && bash submit_campaign.sh"; exit 1
fi

. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$WORK_ROOT/collect"
apptainer exec --no-home --cleanenv "${BINDS[@]}" \
  "$SIF" python3 /campaign/collect_results.py /work/campaign_summary.md /work
echo "SUMMARY: $WORK_ROOT/campaign_summary.md"
