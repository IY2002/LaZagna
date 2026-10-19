# Where run output goes

SLURM logs: every `*.sbatch` writes `logs/<job-type>/<job-type>_<jobid>[_<task>].{out,err}`.

| folder | written by |
|---|---|
| `exp/` | `experiment.sbatch` (fixed-configuration experiments) |
| `worker/` | `worker_array.sbatch` (Optuna workers) |
| `characterize/` | `characterize.sbatch` |
| `extras/`, `collect/` | `extras.sbatch`, `collect.sbatch` |
| `build/` | `build_lazagna.sbatch` (container image build) |
| `script/` | `run_script.sbatch` (one-off scripts in the container) |
| `fftest/` | `test_fastflow.sbatch` |
| `archive/` | old logs from before this layout (Aug 2026 `Output/`) |

Submit from the repo root (paths are relative to the submit directory). The folders are
tracked via `.gitkeep`, because SLURM won't start a job whose log directory is missing;
`submit_campaign.sh` also recreates them. The log files themselves are git-ignored.

Experiment data lives under the study work dir (default `campaign_work/study/`):
`tasks/` (task lists), `runs/<jobid>/task_<n>/` (per-task VPR work dirs), `results/` (one JSON
per task, read by `campaign/analyze.py`), and `archive/` (superseded result sets).

`campaign_work/` (git-ignored) top level:
- `prep_cache/`: shared synthesis + pack cache (mounted as `/prep`)
- `study/`: the fixed-configuration experiments
- `study_optuna/`: the structured layout searches
- `characterization_final/`: the characterization table behind the design selection
- `archive/`: old campaigns, probes and superseded characterizations
