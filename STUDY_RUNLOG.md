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

## State (2026-10-11 23:10)
- Batches 1–3 done (~200 results). Findings v3 are in STUDY_RESULTS.md. The 10-seed RQ2
  confirmation shows type-dedicated layers +1.8..+5.3% WL on 6/6 designs.
- Optuna: tpu and stereovision1 done (44/45 complete); attention ~40/45 (13967295). Summary in
  docs/study/optuna_summary.md. The search rediscovers type separation.
- Validation of the Optuna top 3 per design at 5 seeds = 13968062 (9 tasks).
- Batch 4 = 13968213 (64 tasks, %13): split_types for every RQ1 design; the recommended arch
  (split + v=0.1, tag rec) for 20 designs; delay sensitivity (0.3/1.5/3.0) for aligned and
  recommended on 6 designs (tag delay).
- mcml/lenet/tdarknet: OpenFPGA post-synthesis `read_blif` crash (dict::at). Probe =
  13968117 (campaign_work/blif_probe, runs our yosys script on mcml, then read_blif).
- Pending large RQ1: clstm_like.small, gemm_layer (batch 2, still running).

## Next
- Read the mcml probe (read.log); fix the BLIF issue if it comes from our flow (suspect: ROM INIT
  params or the async2sync output), then re-prep mcml/lenet/tdarknet and add them to RQ1.
- When batch 4 lands: analyze.py → 'Recommended 3D architecture vs 2D' and 'Sensitivity to
  inter-layer delay' sections; update STUDY_RESULTS.md (this is the paper's synthesis claim).
- Add clstm/gemm rec runs when their RQ1 finishes.
- Final write-up (by ~15:00 on 10-12): consolidate STUDY_RESULTS.md into paper-ready sections
  (method, results per RQ, recommended architecture, limitations, reproduction).
