#!/bin/bash
# One-off end-to-end check of the fast flow (campaign/test_fastflow.py).
#   sbatch -A gts-<PI> test_fastflow.sbatch          (TEST_DESIGN=koios/eltwise_layer default)
#SBATCH --job-name=lazagna_fftest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH -q inferno
#SBATCH --time=04:00:00
#SBATCH --output=logs/fftest/fftest_%j.out
#SBATCH --error=logs/fftest/fftest_%j.err
set -u
module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }
CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:-$CAMPAIGN/campaign_work/fftest_${SLURM_JOB_ID}}"
. "$CAMPAIGN/campaign/binds.sh"
lazagna_binds "$WORK_ROOT/w"
for v in TEST_DESIGN SEEDS TALL CW SKIP_EQUIV; do
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/test_fastflow.py
echo "rc=$? $(date -Is)"
