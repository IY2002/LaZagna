# 3D FPGA Architecture Study: Results

Status: **in progress, preliminary**. The autonomous run updates this file as experiments
finish. Numbers come from `docs/study/tables.md`, which `campaign/analyze.py` regenerates from
`campaign_work/study/results/*.json`. Assumptions are in STUDY_ASSUMPTIONS.md.

Setup in one paragraph: VTR-style `dsp_bram` architecture with 4-row DSPs and 6-row
single-port BRAMs, a fixed 75/12.5/12.5 column mix, and channel width 300. Each design gets
a 2D device sized so its binding resource is 80% used, and a 2-layer 3D device with the same
tile count. 3D switch blocks connect the layers (LaZagna). Synthesis and packing happen once
per design, then VPR place-and-route runs with 5 paired seeds. Gains are reported as
mean ± 95% CI over seeds.

## Key findings so far

1. **RQ1: 3D shortens wires on every design and speeds up the hard-block-heavy ones.**
   Over 17 designs, 3D reduces routed wirelength on **17/17 (geomean +7.6%)** and CPD by
   **+3.9% geomean** (11/17 better; the CPD intervals are wide). The size of the gain
   tracks how much of the design's area is hard blocks: Spearman **+0.71** for the WL gain
   (+0.44 for CPD). It is anti-correlated with CLB utilization (−0.55). The interpretation:
   in 2D, tall DSP/BRAM columns push the logic apart, and a second layer brings the logic
   that talks to those columns closer. Logic-dominated designs (bgm, blob_merge, LU8PEEng)
   gain ≈0 CPD and +2–6% WL; sparse, BRAM-dominated spmv gains +24.5% CPD and +16% WL.
2. **RQ2: where hard blocks sit within a layer matters; which layer they sit on barely does.**
   Against evenly spread, layer-aligned hard-block columns, clustering the hard blocks hurts
   consistently: center −7.0% WL / −5.3% CPD, edges −12.1% WL / −4.7% CPD (mean over 6
   designs, up to −28% WL). Re-arranging them *vertically* is within noise: all hard blocks
   on one layer (hb_one_layer) gives +0.2% CPD / −0.2% WL, DSP and BRAM on separate layers
   (split_types) gives −1.5% / +0.1%, and staggering the layers gives −0.9% / −0.6%.
   **Implication: a logic-only die stacked on a hard-block die costs ≈nothing in
   performance,** which opens heterogeneous integration (e.g. hard blocks on a different
   process node). Being confirmed on 6 more designs (batch 2).
3. **RQ3: vertical links can be cut by 4× with little loss, if they're cut per switch block.**
   Keeping every switch block 3D but letting only 25% of its channels cross (v = 0.25)
   changes CPD by −4..+2% (within noise) and WL by ≤ ±1%. Making only 25% of the switch
   blocks 3D (p = 0.25, the same link count) costs 0.1–2.7% WL, and p = 0.1 costs 2–8% WL.
   **For a fixed vertical-link budget, spread thin links everywhere rather than full links
   at a few sites.** v = 0.05 and 0.1 are running (batch 2) to find where it breaks down.

## Detailed tables

See `docs/study/tables.md` (regenerated) and figures in `docs/study/figs/`.

## Limitations (so far)

- CPD seed noise is ±4–6% (95% CI), so single-design CPD differences under ~5% are not
  significant. The WL conclusions are much tighter (±1–3%).
- Single architecture family (one CLB, one routing architecture, channel width 300). Two layers only.
- BRAM read-enable and write-port approximations (STUDY_ASSUMPTIONS.md) affect functional
  behavior, not routing structure.
