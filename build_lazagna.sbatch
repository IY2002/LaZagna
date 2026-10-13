#!/bin/bash
# ============================================================================
# Build the LaZagna Apptainer image on a PACE COMPUTE node (Apptainer is disabled
# on login nodes). Produces lazagna.sif next to this script.
#   Normally invoked for you by submit_campaign.sh when the .sif is missing.
#   Standalone:  sbatch -A gts-<PI> build_lazagna.sbatch
# ============================================================================
#SBATCH --job-name=lazagna_build
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G                 # OpenFPGA/VTR9 parallel C++ build is the RAM driver
##SBATCH -A gts-CHANGEME          # DISABLED: submit_campaign.sh passes -A; or drop one '#' to hardcode
#SBATCH -q inferno                # charged, 21-day wall (embers = free, 8h; build fits in 8h too)
#SBATCH --time=03:00:00           # build is ~1 h; margin for a slow node
#SBATCH --output=logs/build/build_%j.out
#SBATCH --error=logs/build/build_%j.err
# ============================================================================
set -u

module load apptainer 2>/dev/null || true   # may already be on PATH (Lmod said 'unknown
                                            # module' on run 11659290 yet the build worked)
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

DEF="${DEF:-$SLURM_SUBMIT_DIR/lazagna.def}"
SIF="${SIF:-$SLURM_SUBMIT_DIR/lazagna.sif}"

[ -f "$DEF" ] || { echo "FATAL: missing $DEF"; exit 1; }

# Keep Apptainer's build scratch/cache off the small /tmp and $HOME (use project storage).
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$SLURM_SUBMIT_DIR/.apptainer_tmp}"
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$SLURM_SUBMIT_DIR/.apptainer_cache}"
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"

echo "BUILD START $(date -Is)  def=$DEF  sif=$SIF"

# PACE compute-node builds are unprivileged (their KB shows no sudo). Try plain first,
# fall back to --fakeroot only if the unprivileged build errors on permissions.
if apptainer build "$SIF" "$DEF"; then
  echo "BUILD OK (unprivileged) $(date -Is)"
elif apptainer build --fakeroot "$SIF" "$DEF"; then
  echo "BUILD OK (--fakeroot) $(date -Is)"
else
  echo "BUILD FAILED $(date -Is). If it OOMed, lower BUILD_JOBS in lazagna.def or raise --mem."
  exit 1
fi

echo "SIF ready: $SIF"
ls -lh "$SIF"
