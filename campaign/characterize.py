# Benchmark characterization: synthesize + pack each design ONCE (no place, no route) and
# report what device it needs under the fixed 75 / 12.5 / 12.5 column composition.
#
# Why. The placement study only says something when hard blocks are actually contended.
# The 14 Aug study came back null on eltwise (11 DSPs against 272 slots), and the 17 Sep
# characterization "failed" on most designs only because they did not fit a fixed 36x36
# device and the script never read VPR's demand. This version packs against an auto-sized
# device, so it always gets the real demand, and then sizes the 2D device to the design
# ("2D sets the size") and the 3D device to match the 2D tile count.
#
# It goes through lazagna_optuna.prepare(), i.e. the same shared cache (/prep) the studies
# use, so the synthesis paid for here is never paid again by a study.
#
# One design per SLURM array task (CHAR_INDEX), then `--summarize` prints the table.
# env: CHAR_DESIGNS  space/comma separated "suite/name" (suite = koios | vtr), default below
#      CHAR_INDEX    which design this task handles (set from SLURM_ARRAY_TASK_ID)
#      TALL          1 (default) = 4-tall DSP / 6-tall BRAM templates, 0 = 1x1 templates
#      TARGET_UTIL   utilization of the binding resource on the 2D device (default 0.8)
import json
import os
import re
import shutil
import sys
import time

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
os.chdir(ROOT)
sys.path[:0] = [CODE, ROOT]

from lazagna_optuna import SearchConfig, prepare, size_devices, column_counts

SUITES = {"koios": "benchmarks/koios", "vtr": "benchmarks/VTR_benchmarks"}
DEFAULT_DESIGNS = [
    # Koios (deep-learning, DSP/BRAM-heavy). Smaller variants first: these are the ones
    # that can afford many routed trials.
    "koios/eltwise_layer", "koios/conv_layer", "koios/gemm_layer", "koios/attention_layer",
    "koios/reduction_layer", "koios/dla_like.small", "koios/tpu_like.small.os",
    "koios/tpu_like.small.ws", "koios/bwave_like.fixed.small", "koios/clstm_like.small",
    "koios/dnnweaver", "koios/lenet", "koios/bnn", "koios/softmax", "koios/spmv",
    "koios/robot_rl", "koios/conv_layer_hls", "koios/tdarknet_like.small",
    # VTR designs with multipliers and/or memories.
    "vtr/mcml", "vtr/LU8PEEng", "vtr/LU32PEEng", "vtr/stereovision0", "vtr/stereovision1",
    "vtr/stereovision2", "vtr/bgm", "vtr/raygentop", "vtr/mkPktMerge", "vtr/mkDelayWorker32B",
    "vtr/mkSMAdapter4B", "vtr/blob_merge", "vtr/boundtop", "vtr/ch_intrinsics", "vtr/or1200",
    "vtr/diffeq1", "vtr/diffeq2", "vtr/sha", "vtr/arm_core", "vtr/spree",
    "vtr/matmul_8x8_fp16", "vtr/tpu.16x16.int8",
]
_raw = os.environ.get("CHAR_DESIGNS", "")
DESIGNS = [d for d in re.split(r"[,\s]+", _raw) if d] or DEFAULT_DESIGNS
TALL = os.environ.get("TALL", "1") != "0"
OUT = os.path.join(WORK, "char")


def base_cfg(bdir: str) -> SearchConfig:
    tdir = "dsp_bram_tall" if TALL else "dsp_bram"
    cfg = SearchConfig(lazagna_root=ROOT, benchmark_dir=bdir, is_verilog=True,
                       arch_type="combined", search_mode="columns", prep_dir="/prep",
                       template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
                       template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml")
    if os.environ.get("TARGET_UTIL"):
        cfg.target_util = float(os.environ["TARGET_UTIL"])
    return cfg


def bench_dir(entry: str):
    """Single-design dir on the writable host work dir, so prepare() sees exactly one .v."""
    suite, name = entry.split("/", 1)
    src = os.path.join(ROOT, SUITES[suite], name + ".v")
    if not os.path.exists(src):
        return None
    d = os.path.join(WORK, "bench", "char_" + name)
    dst = os.path.join(d, name + ".v")
    if not os.path.exists(dst):
        os.makedirs(d, exist_ok=True)
        shutil.copy(src, dst + ".tmp")
        os.replace(dst + ".tmp", dst)
    return d


def characterize(entry: str) -> dict:
    name = entry.split("/", 1)[1]
    rec = {"design": entry, "tall": TALL}
    bdir = bench_dir(entry)
    if bdir is None:
        return {**rec, "error": "source .v not found"}
    cfg = base_cfg(bdir)
    t0 = time.time()
    try:
        meta = prepare(cfg)
    except Exception as e:
        return {**rec, "error": f"{type(e).__name__}: {e}", "t_s": round(time.time() - t0)}
    rec.update(demand=meta["demand"], synth=meta.get("synth", {}),
               t_synth_s=meta.get("t_synth_s"), t_pack_s=meta.get("t_pack_s"))
    try:
        sz = size_devices(cfg, meta["demand"])
    except Exception as e:
        return {**rec, "error": f"sizing: {e}"}
    util = {t: round(meta["demand"].get(t, 0) / sz["cap_2d"][t], 3) for t in sz["cap_2d"] if sz["cap_2d"][t]}
    rec.update(sizing={k: v for k, v in sz.items() if k != "demand"}, util_2d=util,
               cols_per_layer_3d=column_counts(cfg, sz["width"] - 2))
    return rec


def fmt_row(r: dict) -> str:
    if "error" in r:
        return f"{r['design']:30} FAILED: {r['error'][:110]}"
    d, s, u = r["demand"], r["sizing"], r["util_2d"]
    binding = max(("clb", "complex_dsp", "spram"), key=lambda t: u.get(t, 0))
    sy = r.get("synth") or {}
    mem = (f"{sy.get('memories',0)}/{sy.get('soft_tdp',0)}/{sy.get('soft_rom',0)}/{sy.get('soft_other',0)}"
           if sy else "-")
    return (f"{r['design']:30} {d.get('clb',0):7d} {d.get('complex_dsp',0):5d} {d.get('spram',0):5d}  "
            f"{s['width_2d']:4d}x{s['height_2d']:<4d} 2x{s['width']}x{s['height']:<5d} "
            f"{100*u.get('clb',0):5.1f} {100*u.get('complex_dsp',0):5.1f} {100*u.get('spram',0):5.1f}  "
            f"{binding:11s} {(r.get('t_synth_s') or 0)/60:6.1f} {(r.get('t_pack_s') or 0)/60:5.1f}  {mem}")


def summarize():
    rows = []
    for f in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if f.endswith(".json"):
            rows.append(json.load(open(os.path.join(OUT, f))))
    print(f"templates: {'tall (DSP 4, BRAM 6)' if TALL else '1x1'}; 2D sized so the binding "
          f"resource is at the target utilization; 3D matches the 2D tile count over 2 layers.")
    print(f"{'design':30} {'CLB':>7} {'DSP':>5} {'BRAM':>5}  {'2D':9} {'3D':13} "
          f"{'CLB%':>5} {'DSP%':>5} {'BRM%':>5}  {'binding':11} {'synth':>6} {'pack':>5}  "
          f"mems/soft:tdp/rom/async")
    ok = [r for r in rows if "error" not in r]
    # Most useful first: hard blocks well used AND logic not starved (both matter for a
    # placement study), then cheapest (smaller devices allow more routed trials).
    def score(r):
        u = r["util_2d"]
        return (-min(max(u.get("complex_dsp", 0), u.get("spram", 0)), u.get("clb", 0)),
                r["sizing"]["tiles_2d"])
    for r in sorted(ok, key=score) + [r for r in rows if "error" in r]:
        print(fmt_row(r))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if "--summarize" in sys.argv:
        summarize()
        sys.exit(0)
    idx = os.environ.get("CHAR_INDEX")
    todo = [DESIGNS[int(idx)]] if idx is not None else DESIGNS
    for entry in todo:
        r = characterize(entry)
        name = entry.replace("/", "__")
        with open(os.path.join(OUT, name + ".json"), "w") as f:
            json.dump(r, f, indent=1)
        print(fmt_row(r), flush=True)
