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

## State (2026-10-12 12:40)
- The loop stalled from ~22:50 to 12:20 (scheduled wakeups did not fire). All earlier jobs had finished.
- BLIF check: the techmap fix changed netlists slightly (~0.5% CLB on some designs) → the
  earlier results mix synthesis versions. FINAL RERUN = job 13978112 (279 tasks, %28, longest
  first) into campaign_work/study/results/. Old results are in results_prefinal/.
- Excluded from the final set: gemm (7 h/task), lenet (flow bug, fix deferred; 6.7 h P&R),
  tdarknet (455×398 device).

## Next
- DO NOT edit task/designs/* until every design in the final rerun has prepped (synthesis
  cache key). After the rerun completes: apply the lenet dfflegalize-order fix and commit.
- As results land: analyze.py → rewrite STUDY_RESULTS.md from the final tables (paper-ready).
- Deadline 16:45.
