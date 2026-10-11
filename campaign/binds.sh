# Sourced by every campaign sbatch script. Sets up the per-job writable dirs and the BINDS
# array for `apptainer exec`.
#
#   . "$CAMPAIGN/campaign/binds.sh"
#   lazagna_binds "$W"            # $W = this job's private work dir
#   apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/<script>.py
#
# Code comes from the HOST checkout, not the image: the image only provides the built
# OpenFPGA/VTR binaries and the Python venv. So editing Python, flow templates or arch
# templates needs no image rebuild (rebuilding OpenFPGA takes hours). Rebuild only when
# lazagna.def or the OpenFPGA submodule changes.
#   /code                      host repo, read-only, first on PYTHONPATH (lazagna_optuna, ...)
#   /opt/LaZagna/lazagna       host flow scripts (main.py, run_flow.py, ...)
#   /opt/LaZagna/task/config_templates, task/designs (yosys.ys, BRAM/DSP maps),
#   setup_files, scripts       host copies
#   /opt/LaZagna/arch_files    per-job writable copy; templates refreshed from the host
#   /prep                      shared synthesis + pack cache (campaign_work/prep_cache)
# Requires CAMPAIGN, SIF, WORK_ROOT.

lazagna_binds() {
  local W="$1"
  mkdir -p "$W"/{arch_files,base_rrg,rrg_3d,tasks_run,results} "$WORK_ROOT"/{journal,bench}
  # Synthesis + pack cache shared by ALL campaigns (keyed by benchmark + block definitions),
  # so characterization pays for synthesis once and every later study reuses it.
  mkdir -p "$CAMPAIGN/campaign_work/prep_cache"
  # Generated arch files live next to the templates, so the dir must be writable per job.
  # Templates are refreshed from the host every start so template edits take effect.
  mkdir -p "$W/arch_files/templates"
  cp -a "$CAMPAIGN/arch_files/templates/." "$W/arch_files/templates/"

  BINDS=(-B "$W/arch_files:/opt/LaZagna/arch_files"
         -B "$W/base_rrg:/opt/LaZagna/base_rrg"
         -B "$W/rrg_3d:/opt/LaZagna/rrg_3d"
         -B "$W/tasks_run:/opt/LaZagna/tasks_run"
         -B "$W/results:/opt/LaZagna/results"
         -B "$WORK_ROOT:/work"
         -B "$CAMPAIGN/campaign_work/prep_cache:/prep"
         -B "$CAMPAIGN/campaign:/campaign"
         -B "$CAMPAIGN:/code:ro"
         -B "$CAMPAIGN/lazagna:/opt/LaZagna/lazagna:ro"
         -B "$CAMPAIGN/task/config_templates:/opt/LaZagna/task/config_templates:ro"
         -B "$CAMPAIGN/task/designs:/opt/LaZagna/task/designs:ro"
         -B "$CAMPAIGN/setup_files:/opt/LaZagna/setup_files:ro"
         -B "$CAMPAIGN/scripts:/opt/LaZagna/scripts:ro")
  export APPTAINERENV_PYTHONPATH="/code"
  export APPTAINERENV_LAZAGNA_CODE="/code"
  export APPTAINERENV_WORK="/work"
}
