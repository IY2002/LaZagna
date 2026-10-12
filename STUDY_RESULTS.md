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
   Over 20 designs, 3D reduces routed wirelength on **20/20 (geomean +8.2%)** and CPD by
   **+3.8% geomean** (13/20 better; the CPD intervals are wide). The size of the gain tracks
   how much of the design's area is hard blocks: Spearman **+0.71** for the WL gain (+0.44
   for CPD). It is anti-correlated with CLB utilization (−0.55). The interpretation: in 2D,
   tall DSP/BRAM columns push the logic apart, and a second layer brings the logic that talks
   to those columns closer. Logic-dominated designs (bgm, blob_merge, LU8PEEng) gain ≈0 CPD
   and +2–6% WL; sparse, BRAM-dominated spmv gains +24.5% CPD and +16% WL.
2. **RQ2: where hard blocks sit within a layer matters; which layer they sit on barely does,
   and separating DSP from BRAM by layer helps slightly.** (12 designs, vs evenly spread,
   layer-aligned columns.)
   - Clustering hard blocks hurts: center −5.1% WL / −5.4% CPD, edges −12.1% / −4.7% (up to
     −28% WL). The one exception is arm_core, which has no DSPs.
   - Vertical re-arrangements are within noise for CPD: all hard blocks on one layer gives
     −0.4% CPD / +0.5% WL; layer 1 staggered by half a pitch gives −0.5% / −0.1%.
   - **DSP on one layer and BRAM on the other gives +1.5% WL on average**, positive on 8/12
     designs and significant on 5 (mkDelayWorker32B +5.3 ± 1.9, stereovision2 +4.3 ± 2.0,
     eltwise +3.0 ± 2.2, reduction +2.4 ± 1.1, conv +2.3 ± 1.2), with CPD −0.6% (noise).
   - **Implication:** dedicating layers by function (a logic-only die over a hard-block die,
     or DSP and BRAM on separate dies) costs ≈nothing and can shorten wires. That favors
     heterogeneous 3D integration (different process nodes or IP per die).
3. **RQ3: thin the vertical links per switch block, don't remove switch blocks.** At an
   equal link budget (mean over 6 designs):

   | vertical links kept | fewer 3D switch blocks (CPD / WL) | fewer crossing channels (CPD / WL) |
   |---|---|---|
   | 50% | −1.3% / −0.8% | −0.1% / +0.2% |
   | 25% | −1.8% / −1.8% | −1.1% / +0.2% |
   | 10% | **−5.4% / −6.1%** | **−0.5% / −0.7%** |
   | 5% | – | −0.6% / −2.2% |

   Keeping every switch block 3D with only 5–10% of its channels crossing preserves
   almost all of the 3D benefit (the 2D device is 9–19% worse in WL on these designs). That
   is a 10–20× reduction in inter-die connections (micro-bumps/TSVs/hybrid-bond pads).

## Detailed tables

See `docs/study/tables.md` (regenerated) and figures in `docs/study/figs/`.

## Limitations (so far)

- CPD seed noise is ±4–6% (95% CI), so single-design CPD differences under ~5% are not
  significant. The WL conclusions are much tighter (±1–3%).
- Single architecture family (one CLB, one routing architecture, channel width 300). Two layers only.
- BRAM read-enable and write-port approximations (STUDY_ASSUMPTIONS.md) affect functional
  behavior, not routing structure.
