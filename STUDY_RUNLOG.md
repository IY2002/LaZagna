# Autonomous Study Run Log

Started 2026-10-11 ~20:45 ET; runs for 20 hours (until ~2026-10-12 16:45 ET).
Read at every loop iteration. Update "State" and "Next" before ending each iteration.

## Limits
- At most ~30 concurrent SLURM jobs on gts-chao33 (`squeue -u $USER`). No push; local
  commits on `study-fastflow` only.
- Login node: no apptainer. Container work goes through sbatch, using `campaign/binds.sh`.
- Assumptions go in STUDY_ASSUMPTIONS.md (Decision log); results go in STUDY_RESULTS.md.

## Plan
- **A. Characterization (job 13965227 array + summary 13965228):** read
  `characterize_13965228_0.out`. Pick designs: hard blocks contended (DSP or BRAM ≥ ~25%
  used), synthesizes cleanly, size affordable. Split into SEARCH designs (small or medium,
  routed trials affordable) and EVAL designs (wider set for RQ1).
- **B. RQ1, 3D vs 2D:** routed, 5 seeds, every EVAL design, through `phase_2dvs3d.py`
  (DESIGNS_2DVS3D). Report per-design and geomean gains with seed spread.
- **C. RQ2, hard-block placement:** per SEARCH design, a columns study (placement fidelity)
  plus promote (routed top, Pareto, random set, reference, 2D). Also run a structured set of
  named layouts (aligned, offset/staggered, hard blocks all on one layer, DSP and BRAM on
  separate layers, clustered vs spread), so the findings are interpretable rather than just
  "the optimizer found X". Analyze which layout features correlate with CPD/WL.
- **D. RQ3, vertical connectivity:** sweep 3D switch-block connectivity (e.g. 0.1–1.0) on
  the reference layout, routed, 5 seeds, several designs. Report the knee of the
  CPD/WL-vs-links curve.
- **E. Write-up:** STUDY_RESULTS.md with tables, figures (PNG), and insights for each RQ;
  limitations; reproduce commands.

## State (2026-10-11 21:50)
- Batches 1 and 2: 134 results, 0 errors (gemm/clstm/large RQ1 may still be running). Findings
  are in STUDY_RESULTS.md (RQ1 20 designs; RQ2 12 designs; RQ3 6 designs + strategy table).
- Optuna structured studies restarted with 64 GB workers: tpu_like.small.os = 13967294,
  attention_layer = 13967295, stereovision1 = 13967296 (journal in campaign_work/study_optuna,
  target 45 COMPLETE trials).
- mcml retry (async2sync) = 13967311.

## Next
- When the Optuna studies have ≥30 complete trials each, run analyze_optuna.py via
  run_script.sbatch (WORK_ROOT=campaign_work/study_optuna). Then submit
  tasks_validate.jsonl (copied into campaign_work/study) with experiment.sbatch to get the top
  layouts at 5 seeds.
- RQ2 follow-up (batch 3): split_types is the most interesting layout. Test it with clustering
  per layer (DSP layer spread vs BRAM layer spread), the reverse layer order (BRAM on layer 0),
  and more seeds (10) on the 5 designs where it was significant, to firm up the claim.
- RQ3 follow-up: channel-thinning at p=0.5 vs p=1 (is p=1, v=0.1 better than p=0.2, v=0.5?);
  v=0.05 on conv/eltwise; SB location patterns (perimeter/core/rows/columns) at p=0.25.
- RQ1: add 10 seeds on the 6 designs whose CPD CI crosses zero, if budget allows.
