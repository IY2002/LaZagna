#!/bin/bash
# ============================================================================
# LaZagna campaign EXTRAS job — the non-optuna phases, run once while the worker
# array chews the studies in parallel:
#   smoke  : simple_test.yaml (validates container + binds before anything heavy)
#   phase3 : 3D vs 2D at equal resources, routed, for DESIGNS_2DVS3D (autosized devices)
# (The old phase4 conv/lstm fit check is superseded by the characterization pass.)
# Continue-on-fail between phases. Submitted by submit_campaign.sh.
# ============================================================================
#SBATCH --job-name=lazagna_extras
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH -q inferno
#SBATCH --time=16:00:00
#SBATCH --output=logs/extras/extras_%j.out
#SBATCH --error=logs/extras/extras_%j.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"
[ -f "$WORK_ROOT/campaign.env" ] && . "$WORK_ROOT/campaign.env"   # tunables (SEEDS, CW, HB_*, ...)
W="$WORK_ROOT/extras"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

# Stale-image guard (old .sif lacks the bind mountpoints AND bakes old code).
if ! apptainer exec --no-home --cleanenv "$SIF" test -d /opt/LaZagna/base_rrg; then
  echo "FATAL: lazagna.sif is STALE. rm lazagna.sif && bash submit_campaign.sh"; exit 1
fi

. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$W"

for v in CW SEEDS TARGET_UTIL TALL DESIGNS_2DVS3D; do   # phase 3/4 tunables, if the user set them
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
APP=(apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF")

run_phase() {  # $1 = label ; $2.. = command
  local label="$1"; shift
  echo "==================== $label START $(date -Is) ===================="
  if "$@"; then
    echo "==================== $label OK   $(date -Is) ===================="
  else
    echo "!!!!!!!!!!!!!!!!!!!! $label FAILED (rc=$?, continuing) $(date -Is) !!!!!!!!!!!!"
  fi
}

run_phase "smoke"  "${APP[@]}" python3 /opt/LaZagna/lazagna/main.py \
                     -f /opt/LaZagna/setup_files/simple_test.yaml -v
run_phase "phase3-2dvs3d"   "${APP[@]}" python3 /campaign/phase_2dvs3d.py "${SEEDS:-3}"
echo "EXTRAS DONE $(date -Is)"
