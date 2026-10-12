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

## State (2026-10-11 20:55)
- Batch-1 rerun 13966093: 83/86 clean (0 errors). Remaining: the large RQ1 designs
  (dla_like.small, LU32PEEng, bwave). Tables are in docs/study/tables.md. Findings are in
  STUDY_RESULTS.md (v1).
- Batch 2 = job 13966526 (51 tasks, %14): RQ2 generalization on 6 designs (hb_one_layer,
  split_types, center, staggered); RQ3 v=0.05/0.1 and p=0.5,v=0.5 on 4 designs plus a full sweep
  on conv/eltwise; RQ1 clstm_like.small, mcml, gemm_layer (jobs=2).
- Structured Optuna studies (campaign_work/study_optuna, route fidelity, 3 seeds, 45 trials):
  tpu_like.small.os = 13966528, attention_layer = 13966529, stereovision1 = 13966530 (3 workers each).

## Next
- Harvest batch 2; rerun analyze.py; update STUDY_RESULTS.md.
- Optuna: when the studies finish, extract best structured params plus a parameter
  importance/correlation analysis (cluster/stagger/splits vs CPD/WL). Write
  campaign/analyze_optuna.py, which runs in the container (optuna is not on the host). Validate
  the top 3 layouts per design with 5 seeds via a 'custom' experiment kind (explicit columns).
- If the CPD claims need it: 10-seed reruns of key comparisons (RQ1 on the top designs; RQ2
  hb_one_layer vs aligned).
- Consider an RQ3 extra: SB location patterns (core/perimeter/rows/columns) at p = 0.25.
