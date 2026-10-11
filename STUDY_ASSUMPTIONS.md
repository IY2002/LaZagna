# 3D FPGA Architecture Study: Assumptions and Decisions

Every assumption behind the results produced on the `study-fastflow` branch. When a
result looks surprising, check here first. Items marked **(user)** were decided by Ismael;
everything else was decided during the autonomous run, with the reason given.

## Research questions
1. **RQ1. 3D vs 2D at equal resources:** CPD and wirelength gain of a 2-layer device over
   a 2D device with the same tile count and block counts.
2. **RQ2. Hard-block placement across layers:** which arrangements of DSP/BRAM columns on
   the two layers help, and why.
3. **RQ3. Vertical connectivity vs cost:** CPD and wirelength against the fraction of
   3D switch-block connections (fewer inter-layer links mean cheaper bonding).
   The sampler and batch-width ablation is out of scope **(user)**.

## Architecture
- Logic block: unchanged from the LaZagna `dsp_bram` templates (10× fracturable 6-LUT CLB).
- Hard blocks are tall: DSP (`complex_dsp`) is 4 rows, BRAM (`spram`) is 6 rows **(user)**.
  Templates live in `arch_files/templates/dsp_bram_tall/`. Pins use VTR's `spread` pattern,
  because the original single-row custom pin lists don't carry over to tall tiles.
- Column composition is fixed at 75% CLB, 12.5% DSP, 12.5% BRAM columns per layer, for
  every benchmark **(user / Ismael)**. Per layer, the DSP and BRAM column counts are rounded
  and CLB takes the remainder.
- Channel width is 300 for every run, both 2D and 3D (lab standard) **(user)**.
- The BRAM is single-port (one address); that is the architecture as given. There is no LUTRAM.
- The inter-layer delay ratio is 0.739 unless a study varies it (LaZagna default).

## Device sizing
- **2D sets the size (user):** the 2D device is the smallest near-square grid (aspect
  0.8–1.25) on which every block type is at most 80% used.
- The 3D device has two layers whose combined tile count is as close as possible to the 2D
  device's, among grids that also fit the design. For tiny or IO-bound designs no such grid
  exists, so the smallest 3D grid that fits is used and the 3D device ends up larger. Those
  designs are not used for RQ1.
- Interior heights are multiples of 12 (the LCM of the 4- and 6-row block heights), so
  tall-block columns tile exactly with no leftover rows.
- IO capacity is 8 per perimeter tile, on both layers in 3D.

## Synthesis (LaZagna Yosys flow, `task/designs/`)
- **Top module:** given to Yosys explicitly. It comes from LaZagna's table, or is inferred as
  the module no other module instantiates. dnnweaver's top is `cl_wrapper`, not the stale
  table entry `dnnweaver2_controller`.
- **VTR benchmark files:** the pasted VTR primitive models are handled with `-nooverwrite`
  (the design's own definition wins) and by removing `keep_hierarchy`.
- **ROMs map to BRAM (user).** Initialization contents are accepted; VPR does not use them.
- **Small memories still go to BRAM (user).** With no LUTRAM, a BRAM is cheaper than flip-flops.
- **Two write ports are merged into one (user).** Assumption: a design never writes from both
  ports in the same cycle. Address, data and enable come from whichever port writes
  (`merge_write_ports.py`). Read ports are kept, and Yosys duplicates the BRAM when two read
  ports are used.
- **BRAM read enable is approximated.** RAMs written as "if write, write; else read" have a
  read enable. The BRAM has no read-enable pin, so the enable is accepted and ignored:
  during a write cycle the output shows the old data instead of holding its value. This
  affects functional behavior only, not timing paths or area beyond a hold mux.
- **Asynchronous-read memories stay in soft logic.** A synchronous BRAM can't implement
  them; on real FPGAs they would go to LUTRAM.
- Excluded benchmarks: boundtop (multiply-driven nets in the source), tpu.16x16.int8
  (VTR's two-process `dual_port_ram` model yields multiply-driven registers), ch_intrinsics
  (undeclared `wen`/`ren` in its RAM, so the RAM never writes), matmul_8x8_fp16 (needs a
  floating-point MAC hard block).

## Place and route
- Packing happens once per benchmark, on an auto-sized 2D device. Because the block
  definitions are identical, the `.net` is reused for every layout, both devices and every
  seed (`--verify_file_digests off`). Checked on eltwise: the regular flow with its own
  packing gave a bit-identical routed CPD and wirelength for seed 1.
- Placement uses `cube_bb` with VPR defaults otherwise.
- Seeds are a fixed list (1..N), the same for every trial, reference and baseline, so
  comparisons are paired. Reported numbers are geometric means over the seeds.
- The OpenFPGA backend (fabric, Verilog, bitstream) is skipped. Only VPR metrics are used.

## Metrics and statistics
- CPD is "Final critical path delay"; WL is "Total wirelength" (post-route).
- The search fidelity uses VPR's placement estimates ("Placement estimated critical path
  delay", final BB wirelength). Promoted candidates are routed, and the rank correlation
  (Spearman) between placement estimate and routed result is reported for every study.
- Improvement % is (baseline − value) / baseline, with the baseline being the 2D device (RQ1)
  or the evenly spread 3D reference (RQ2/RQ3).

## Decision log
Entries are added during the run (date, decision, reason).

- 2026-10-11: branch `study-fastflow` created; work committed locally and not pushed **(user)**.
- 2026-10-11: **Design selection, batch 1** (from characterization v2). RQ2 layout designs:
  tpu_like.small.os, attention_layer, stereovision1, robot_rl, conv_layer, arm_core. These have
  contended hard blocks (DSP and/or BRAM at ≥ ~20–80% use) and small devices (≤ ~7.3k tiles),
  so many routed runs are affordable. RQ3 connectivity designs: the first four of those. RQ1:
  16 small/medium designs plus 4 large ones (dla_like.small, LU32PEEng, spmv,
  bwave_like.fixed.small). Excluded from RQ1: designs whose 3D device can't match the 2D tile
  count (tiny or IO-bound: raygentop, diffeq1/2, sha, mkSMAdapter4B, mkPktMerge, or1200,
  conv_layer_hls, which is 100% IO-bound) and designs whose synthesis is broken (see above).
  dnnweaver (2×167×158 3D) is deferred for cost.
- 2026-10-11: **Seeds:** 5 for every fixed-configuration experiment (RQ1–RQ3); 3 for Optuna search trials.
- 2026-10-11: **RQ2 named layouts:** aligned (reference), staggered (layer 1 shifted half a pitch),
  hb_one_layer (all hard blocks on layer 0), split_types (DSP on layer 0, BRAM on layer 1),
  center, edges, center_edges (layer 0 center, layer 1 edges). All keep the reference's exact
  block totals.
- 2026-10-11: **RQ3 knobs:** percent_connectivity ∈ {0.1, 0.25, 0.5, 0.75, 1.0} (fraction of
  switch blocks that are 3D, repeated_interval placement) at full per-switch-block vertical
  connectivity, plus vertical_connectivity ∈ {0.25, 0.5} (fraction of channels crossing) at
  connectivity 1.0. Delay ratio fixed at 0.739.
- 2026-10-11: **Search fidelity for RQ2 Optuna studies: routed** (not placement estimates).
  The chosen designs route in minutes, and on eltwise the placement-estimated CPD ranked
  layouts poorly (Spearman 0.40 over 4 trials).
