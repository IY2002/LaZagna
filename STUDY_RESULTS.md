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
2. **RQ2: spread hard blocks within a layer, and give each hard-block type its own layer.**
   (12 designs at 5 seeds, 6 of them confirmed at 10 seeds, plus a 5-parameter Optuna search
   on 3 designs.)
   - **Clustering hard blocks is the dominant penalty.** Center −5.1% WL / −5.4% CPD, edges
     −12.1% / −4.7% (up to −28% WL). In the Optuna search, the `cluster` parameter has the
     strongest negative rank correlation with the WL gain in every design (−0.27, −0.57, −0.79).
   - **Type-dedicated layers (DSP on one layer, BRAM on the other) shorten wires
     consistently:** +1.8 to +5.3% WL on 6/6 designs at 10 seeds (CI about ±1%), with CPD
     neutral. Layer order doesn't matter: BRAM on the bottom gives +2.1 to +5.3%. Over the 12
     designs at 5 seeds it averages +1.5% WL.
   - **The search rediscovers this without being told:** its best layouts put most BRAM
     columns on one layer and most DSP columns on the other (e.g. BRAM 12–16 of 16 on layer 0
     with DSP only 4–7 of 16) at low clustering, for +2–3% WL at 3 seeds.
   - **Putting all hard blocks on one layer (a logic-only die) is ≈ neutral:** −2..+3% WL
     depending on the design and which layer, with CPD within noise. Staggering the layers
     does nothing (−0.1% WL).
   - **Mechanism (interpretation):** with types on separate layers, each layer has twice as
     many columns of its type at half the pitch, so any logic is laterally closer to its
     nearest DSP (on one die) and its nearest BRAM (on the other), one vertical hop away.
   - **Implication:** function-dedicated dies (a DSP die and a BRAM die, or hard blocks
     separated from logic) cost nothing in performance and slightly reduce wiring. That
     supports heterogeneous 3D integration.
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
   Mixed strategies at the same 10% budget fall in between (p 0.5 × v 0.2: −1.5% WL;
   p 0.2 × v 0.5: −3.3%). **The more evenly the vertical links are spread, the better.**
   - **Where 3D switch blocks go matters at a fixed budget** (p = 0.25): evenly interleaved
     or core placement costs −0.1 to −4.9% WL, rows or columns cost −2 to −8%, and
     concentrating them at the perimeter costs **−11 to −22% WL and up to −40% CPD**. Vertical
     links belong distributed over the core of the fabric, not at its edges.

## Detailed tables

See `docs/study/tables.md` (regenerated) and figures in `docs/study/figs/`.

## Limitations (so far)

- CPD seed noise is ±4–6% (95% CI), so single-design CPD differences under ~5% are not
  significant. The WL conclusions are much tighter (±1–3%).
- Single architecture family (one CLB, one routing architecture, channel width 300). Two layers only.
- BRAM read-enable and write-port approximations (STUDY_ASSUMPTIONS.md) affect functional
  behavior, not routing structure.
