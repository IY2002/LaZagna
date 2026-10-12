# Architectural Exploration of Two-Layer 3D FPGAs with LaZagna: Results

Status: **final rerun in progress.** Every number below will be regenerated from the final
single-synthesis-version results (`campaign_work/study/results/`) by `campaign/analyze.py`
into `docs/study/tables.md`, with figures in `docs/study/figs/`. Sections marked ⟨pending⟩
are filled in once the final rerun completes. The pre-final findings (mixed synthesis
versions) are in git history (commit bb8815a and later). Assumptions are in STUDY_ASSUMPTIONS.md.

## 1. Method

**Architecture.** A VTR-style `dsp_bram` fabric:
- CLBs with 10 fracturable 6-LUTs;
- 4-row DSP blocks (one 27×27 or two 18×19 multipliers);
- 6-row single-port 20 Kb BRAMs (512×40, 1K×20 or 2K×10);
- a fixed column mix of 75% CLB, 12.5% DSP and 12.5% BRAM;
- channel width 300;
- LaZagna 3D switch blocks between two layers, with an inter-layer delay ratio of 0.739
  unless stated otherwise.

**Equal-resource comparison.** For each design, the 2D device is the smallest near-square
grid on which every block type is at most 80% used. The 3D device has two layers whose total
tile count matches the 2D device. Interior heights are multiples of 12, so tall blocks tile
exactly.

**Flow.**
- Yosys synthesis and VPR packing run once per design. The synthesis is LaZagna's flow with
  fixes for VTR primitives, ROMs mapped to BRAM, and single-write-port memories.
- The packed netlist is reused for every architecture variant. Routed results were verified
  bit-identical against the full per-run flow.
- Each configuration is placed (`cube_bb`) and routed with VPR on 5 fixed seeds (10 for
  confirmation runs). All comparisons are paired by seed.
- Metrics:
  - CPD is the final critical path delay; for multi-clock designs it is VPR's geomean
    intra-domain period.
  - WL is the routed wirelength.
  - Per-design gains are the mean ± 95% t-interval over seeds; cross-design summaries are
    geometric means.

**Benchmarks.** Koios (deep-learning, DSP/BRAM-heavy) and VTR designs, chosen by their
measured hard-block demand in a synthesis+pack characterization of 40 candidates. §6 lists
the exclusions and their reasons.

## 2. RQ1: 3D vs 2D at equal resources ⟨pending final numbers⟩

## 3. RQ2: hard-block placement across layers ⟨pending final numbers⟩

## 4. RQ3: vertical connectivity vs cost ⟨pending final numbers⟩

## 5. A recommended 3D architecture ⟨pending final numbers⟩

## 6. Limitations and threats to validity

- One architecture family: one CLB, one routing architecture, one channel width, two layers.
- Per-design CPD seed noise is ±4–6% (95% CI); the WL conclusions are much tighter (±1–3%).
- **Memory-mapping approximations:** write ports are merged, and the BRAM read enable is
  ignored. This changes some designs' functional behavior but not their routing structure.
  Asynchronous-read memories stay in soft logic, because the architecture has no LUTRAM.
- **Excluded designs:**
  - gemm_layer: about 7 h per routed configuration (pre-final RQ1 result only);
  - lenet: synthesis-flow bug found late, fixed after the final run;
  - tdarknet_like.small: 3005 BRAMs require a 455×398 device;
  - boundtop and tpu.16x16.int8: multiply-driven nets in the source;
  - ch_intrinsics: benchmark bug (undeclared RAM enables);
  - matmul_8x8_fp16: needs a floating-point MAC hard block;
  - tiny or IO-bound designs whose 3D device can't match the 2D tile count.
- The structured Optuna search ran on an earlier synthesis version; its top layouts are
  re-validated on the final flow.

## 7. Reproduction

```bash
# characterization (synthesis + pack, all candidates)
CHARACTERIZE=1 bash submit_campaign.sh
# fixed-configuration experiments (task list = campaign_work/study/tasks_final.jsonl)
sbatch -A <acct> --array=0-278%28 \
  --export=ALL,WORK_ROOT=$PWD/campaign_work/study,TASKS=$PWD/campaign_work/study/tasks_final.jsonl \
  experiment.sbatch
# analysis (host, needs matplotlib)
python3 campaign/analyze.py campaign_work/study docs/study
```
