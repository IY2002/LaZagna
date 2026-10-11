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

## State
- Characterization v2 (job 13965227/13965228): 36/40 done at 21:05; gemm, clstm.small, mcml,
  lenet still synthesizing. Table in characterize_13965228_0.out when done.
- Batch 1 (job 13965777, 86 tasks, %24): RQ2 layouts (6 designs × 7), RQ3 connectivity
  (4 designs × 6), RQ1 (20 designs). Results go to campaign_work/study/results/*.json.
- New runner: campaign/experiment.py + experiment.sbatch (task file, one JSON per line).

## Next
- Check the first batch 1 results for errors (exp_13965777_*.out). Fix and resubmit failed tasks
  (finished ones are skipped automatically).
- Write campaign/analyze.py: RQ1 table (2D vs 3D per design, geomean, seed spread), RQ2
  table (layout vs aligned), RQ3 curves. Figures to campaign_work/study/figs, copied
  into docs/study_figs for the write-up.
- Launch Optuna column studies (FIDELITY=route) for tpu_like.small.os and attention_layer
  (4 workers each, ~40 trials) once batch 1 has freed slots.
- Add gemm/clstm/mcml/lenet to RQ1 if they characterize cleanly.
