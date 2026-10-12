#!/bin/bash
# ============================================================================
# LaZagna campaign WORKER ARRAY — N parallel SLURM jobs, each contributing optuna
# trials to the shared studies (columns + 3 samplers) via JournalStorage on the
# shared work dir. This is the parallelism: 16 workers = 16 trials in flight.
# Submitted by submit_campaign.sh (which passes -A, --array, and WORK_ROOT).
#
# No overlay: the flow's writable dirs (arch_files, base_rrg, rrg_3d, tasks_run,
# results) are per-worker host dirs bind-mounted over the read-only image paths.
# (Run 11659291 post-mortem: the 50 GB overlay filled -> ENOSPC; sqlite on
# Lustre -> 'disk I/O error'. Both eliminated.)
# ============================================================================
#SBATCH --job-name=lazagna_worker
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G   # 3D RRG generation peaks ~19 GB plus multi-GB file cache (32G -> intermittent kills)
#SBATCH -q inferno
#SBATCH --time=16:00:00
#SBATCH --output=worker_%A_%a.out
#SBATCH --error=worker_%A_%a.err
set -u

module load apptainer 2>/dev/null || true   # PACE: apptainer may already be on PATH
                                            # (run 11659291: Lmod 'unknown module' yet apptainer worked)
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"
[ -f "$WORK_ROOT/campaign.env" ] && . "$WORK_ROOT/campaign.env"   # tunables (SEEDS, STUDIES, ...)
ID="${SLURM_ARRAY_TASK_ID:-0}"
W="$WORK_ROOT/worker_$ID"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

# Stale-image guard: the bind mountpoints below only exist in images built from the
# parallel-v2 .def. An old lazagna.sif also bakes old code. Fail loud, early.
if ! apptainer exec --no-home --cleanenv "$SIF" test -d /opt/LaZagna/base_rrg; then
  echo "FATAL: lazagna.sif is STALE (predates the parallel-campaign update)."
  echo "       rm lazagna.sif && bash submit_campaign.sh   (it rebuilds the image)"
  exit 1
fi

# Per-worker writable dirs + host code binds (no image rebuild for code changes).
. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$W"

# APPTAINERENV_* survives --cleanenv and dodges --env's comma-list parsing (values with
# spaces, e.g. STUDIES, would be mangled there).
export APPTAINERENV_WORKER_ID="$ID"
export APPTAINERENV_SEEDS="${SEEDS:-3}"
export APPTAINERENV_TRIALS_COLUMNS="${TRIALS_COLUMNS:-35}"
export APPTAINERENV_TRIALS_SAMPLER="${TRIALS_SAMPLER:-15}"
export APPTAINERENV_STUDIES="${STUDIES:-columns promote tpe nsga2 random}"
# Batch width for the RQ3 ablation. Empty means "not an ablation run" and study names
# stay unsuffixed; a value gives each width its own study (see campaign/worker.py).
export APPTAINERENV_BATCH="${BATCH:-}"
export APPTAINERENV_CW="${CW:-300}"   # lab standard channel width
# Fast-flow knobs (see campaign/worker.py): placement-only search fidelity, target utilization.
for v in FIDELITY TARGET_UTIL TALL COLUMNS_DESIGN PROMOTE_TOP PROMOTE_RANDOM SEARCH_MODE; do
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
[ -n "${KEEP_RRG:-}" ] && export APPTAINERENV_KEEP_RRG="$KEEP_RRG"

echo "WORKER $ID START $(date -Is)  work=$W"
apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/worker.py
rc=$?
echo "WORKER $ID DONE rc=$rc $(date -Is)"
exit $rc
