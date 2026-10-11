# 3D vs 2D at equal resources (paper headline), for one or more designs.
#
# For each design: synthesize + pack once (shared /prep cache), size the 2D device to the
# design ("2D sets the size": binding resource at TARGET_UTIL), size the 3D device to the
# same total tile count over two layers, then route the evenly spread reference layout on
# both, with the SAME seeds, at the lab-standard channel width.
#
# History: the old version wrote a two-layer layout into the single-die 2D template, so
# the "2D baseline" was two dies with no vertical routing; it never routed at any cw.
# argv: [seeds=3]   env: DESIGNS_2DVS3D ("koios/eltwise_layer"), CW (300), TALL (1),
#                        TARGET_UTIL (0.8)
import os
import re
import shutil
import sys

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
os.chdir(ROOT)
sys.path[:0] = [CODE, ROOT]

from lazagna_optuna import SearchConfig, autosize, reference_columns, _run_one

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CW = int(os.environ.get("CW", "300"))
TALL = os.environ.get("TALL", "1") != "0"
TARGET_UTIL = float(os.environ.get("TARGET_UTIL", "0.8"))
DESIGNS = [d for d in re.split(r"[,\s]+", os.environ.get("DESIGNS_2DVS3D", "koios/eltwise_layer")) if d]
SUITES = {"koios": "benchmarks/koios", "vtr": "benchmarks/VTR_benchmarks"}


def run_design(entry: str) -> bool:
    suite, name = entry.split("/", 1)
    bdir = os.path.join(WORK, "bench", "e2d3d_" + name)
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, name + ".v")
    if not os.path.exists(dst):
        shutil.copy(os.path.join(ROOT, SUITES[suite], name + ".v"), dst)
    tdir = "dsp_bram_tall" if TALL else "dsp_bram"
    base = SearchConfig(lazagna_root=ROOT, benchmark_dir=bdir, is_verilog=True,
                        channel_width=CW, seeds=SEEDS, seed_list=tuple(range(1, SEEDS + 1)),
                        arch_type="combined", search_mode="columns", prep_dir="/prep",
                        target_util=TARGET_UTIL, fidelity="route", run_tag="e2d3d",
                        template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
                        template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml")
    cfg, info = autosize(base)
    print(f"[{name}] demand {info['demand']}: 2D {cfg.width_2d}x{cfg.height_2d} "
          f"({info['tiles_2d']} tiles) vs 3D 2x{cfg.width}x{cfg.height} ({info['tiles_3d']} tiles)",
          flush=True)
    tag = name.replace(".", "").replace("_", "")
    two, err2 = _run_one(cfg, None, f"e2d3d{tag}two", "2d", 1.0, 0.739)
    three, err3 = _run_one(cfg, reference_columns(cfg), f"e2d3d{tag}three", cfg.arch_type, 1.0, 0.739)
    if two is None or three is None:
        print(f"[{name}] FAILED - FLAG. 2D: {err2}\n3D: {err3}", flush=True)
        return False
    (bc, bw), (c, w) = two, three
    print(f"[{name}] cw={CW} seeds={cfg.seed_list}", flush=True)
    print(f"[{name}] 2D: CPD={bc:.4e} s WL={bw:.0f}   3D: CPD={c:.4e} s WL={w:.0f}", flush=True)
    print(f"[{name}] IMPROVEMENT: CPD {100*(bc-c)/bc:+.2f}%   WL {100*(bw-w)/bw:+.2f}%", flush=True)
    return True


if __name__ == "__main__":
    ok = [run_design(d) for d in DESIGNS]
    print(f"PHASE3 DONE ({sum(ok)}/{len(ok)} designs)", flush=True)
    sys.exit(0 if all(ok) else 1)
