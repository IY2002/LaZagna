# End-to-end check of the fast flow on one design (default eltwise, cheap):
#   1. prepare (synthesis + pack once) and autosize the 2D/3D devices
#   2. 3D reference at placement fidelity, then routed, all seeds in parallel
#   3. 2D baseline, routed
#   4. EQUIVALENCE: the regular LaZagna flow (own synthesis + pack) on the same 3D reference
#      device with seed 1 must give the same routed result as the fast flow's seed 1.
#      That is the evidence that reusing one packed netlist is sound.
# env: TEST_DESIGN (koios/eltwise_layer), SEEDS (3), TALL (1), CW (300), SKIP_EQUIV
import json
import os
import shutil
import sys
import time

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
os.chdir(ROOT)
sys.path[:0] = [CODE, ROOT]

from lazagna_optuna import (SearchConfig, autosize, reference_columns, _run_one, column_counts,
                            parse_results)
import dataclasses

DESIGN = os.environ.get("TEST_DESIGN", "koios/eltwise_layer")
SEEDS = int(os.environ.get("SEEDS", "3"))
TALL = os.environ.get("TALL", "1") != "0"
CW = int(os.environ.get("CW", "300"))
SUITES = {"koios": "benchmarks/koios", "vtr": "benchmarks/VTR_benchmarks"}

suite, name = DESIGN.split("/", 1)
bdir = os.path.join(WORK, "bench", "test_" + name)
os.makedirs(bdir, exist_ok=True)
shutil.copy(os.path.join(ROOT, SUITES[suite], name + ".v"), os.path.join(bdir, name + ".v"))
tdir = "dsp_bram_tall" if TALL else "dsp_bram"
base = SearchConfig(lazagna_root=ROOT, benchmark_dir=bdir, is_verilog=True,
                    channel_width=CW, seeds=SEEDS, seed_list=tuple(range(1, SEEDS + 1)),
                    arch_type="combined", search_mode="columns", prep_dir="/prep",
                    template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
                    template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml",
                    run_tag="ffx")


def step(label, fn):
    t0 = time.time()
    print(f"\n=== {label} ===", flush=True)
    out = fn()
    print(f"--- {label}: {time.time() - t0:.0f} s", flush=True)
    return out


cfg, info = step("prepare + autosize", lambda: autosize(base))
print(json.dumps({k: v for k, v in info.items()}, indent=1))
print("3D cols/layer CLB/DSP/BRAM:", column_counts(cfg), " 2D:", column_counts(cfg, cfg.width_2d - 2))


def run(label, arch_type, fidelity, spec="ref"):
    inf = {}
    sp = reference_columns(cfg) if spec == "ref" else None
    m, err = _run_one(cfg, sp, f"ffx{label}", arch_type, 1.0, 0.739, info=inf, fidelity=fidelity)
    print(f"metrics={m} err={err}")
    print(f"setup {inf.get('t_setup_s')} s, total {inf.get('t_total_s')} s, folder {inf.get('folder')}")
    for r in inf.get("per_seed") or []:
        print(f"  seed {r['seed']}: rc={r['rc']} place_cpd={r['place_cpd']} place_wl={r['place_wl']} "
              f"route_cpd={r['route_cpd']} route_wl={r['route_wl']}")
    return m, inf


step("3D reference, placement fidelity", lambda: run("refplace", cfg.arch_type, "place"))
_, ref_route = step("3D reference, routed", lambda: run("refroute", cfg.arch_type, "route"))
step("2D baseline, routed", lambda: run("twod", "2d", "route", spec=None))

if not os.environ.get("SKIP_EQUIV"):
    def equiv():
        c1 = dataclasses.replace(cfg, fast_flow=False, seed_list=(1,), seeds=1)
        m, err = _run_one(c1, reference_columns(c1), "ffxequiv", cfg.arch_type, 1.0, 0.739)
        fast = next((r for r in ref_route.get("per_seed") or [] if r["seed"] == 1), None)
        print(f"regular flow (own synth + pack), seed 1: {m} err={err}")
        if fast:
            print(f"fast flow (shared .net), seed 1:        ({fast['route_cpd']}, {fast['route_wl']})")
            if m and fast["route_cpd"]:
                print(f"CPD diff {100*(fast['route_cpd']-m[0])/m[0]:+.3f}%  "
                      f"WL diff {100*(fast['route_wl']-m[1])/m[1]:+.3f}%")
    step("equivalence: regular flow vs shared .net (seed 1)", equiv)
print("\nTEST DONE", flush=True)
