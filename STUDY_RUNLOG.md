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
- Characterization v2 complete (characterize_13965228_0.out). New since the last snapshot:
  clstm_like.small (148×182, CLB/DSP/BRAM 80/45/45%), gemm_layer (228×230, logic-bound).
  mcml needed the adff2dff fix (re-prep on first use). lenet/tdarknet are excluded.
- Batch 1 RERUN = job 13966093 (86 tasks, %26) after fixing the log-clash corruption. The old
  results are archived in campaign_work/study/results_v0_corrupt_logs (untrusted).
- Untrusted preview from the old batch-1 results: 3D wins WL on 14/14 designs (geomean
  +7.4%); CPD mixed (geomean +2.3%), best on tpu_like.small.os/ws (+7..11%). Layouts: edges
  and center clustering hurt WL a lot on conv/stereovision1; split_types is slightly positive.
- analyze.py works: `python3 campaign/analyze.py campaign_work/study docs/study`.
- New: `structured` search mode (5 interpretable params: dsp_on_l0, bram_on_l0, cluster,
  stagger, band_pos), wired into worker.py via SEARCH_MODE.

## Next
- When the batch-1 rerun frees slots, launch structured Optuna studies (FIDELITY=route, SEEDS=3,
  ~50 trials, 3 workers each) for tpu_like.small.os, attention_layer, stereovision1 and
  conv_layer. WORK_ROOT=campaign_work/study_optuna, campaign.env with SEEDS/TRIALS_COLUMNS/
  STUDIES=columns/FIDELITY=route/SEARCH_MODE=structured; COLUMNS_DESIGN via --export.
- Batch 2 ideas, decided from the batch-1 data: RQ1 adds clstm_like.small, mcml, gemm_layer
  (large, jobs=2); RQ3 adds SB location patterns (core/perimeter/rows/columns) at p≈0.25;
  delay-ratio sensitivity (0.5, 1.0, 1.5) on 3 designs; 5-seed validation of the top
  structured layouts (needs a 'custom' layout kind with explicit columns in experiment.py).
- Run analyze.py, and write STUDY_RESULTS.md once batch 1 is clean.
