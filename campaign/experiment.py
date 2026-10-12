# Generic fixed-configuration experiment runner (RQ1, RQ2 named layouts, RQ3 connectivity).
#
# One SLURM array task = one line of the task file ($TASKS, JSON per line). Each task is
# routed on its design's autosized device with the shared, fixed seed list, and writes
# /work/results/<id>.json. Re-running skips tasks whose result already exists, so a
# resubmission only fills gaps.
#
# Task fields:
#   id       unique name (file name of the result)
#   kind     "rq1"    : 2D baseline vs 3D reference (evenly spread columns, both layers alike)
#            "layout" : one named 3D hard-block arrangement (see LAYOUTS), arch "combined"
#            "conn"   : 3D reference with a given 3D switch-block connectivity
#            "custom" : explicit 3D columns (`columns`: [layer0, layer1]) or structured
#                       params (`structured`: {dsp_on_l0, bram_on_l0, cluster, stagger, band_pos})
#   design   "koios/<name>" | "vtr/<name>"
#   seeds    number of placement seeds (default 5)
#   layout   (layout) name in LAYOUTS
#   conn     (conn) fraction of switch blocks that are 3D (percent_connectivity)
#   vconn    (conn) fraction of channels per 3D switch block that cross layers
#   jobs     parallel VPR runs (default = seeds)
# env: TASKS (path), TASK_INDEX (array index), WORK (/work), TALL (1), CW (300)
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

import dataclasses
from lazagna_optuna import SearchConfig, autosize, reference_columns, column_counts, _run_one
from layout_space import ColumnLayoutSpec, CLB, DSP, BRAM

SUITES = {"koios": "benchmarks/koios", "vtr": "benchmarks/VTR_benchmarks"}
TALL = os.environ.get("TALL", "1") != "0"
CW = int(os.environ.get("CW", "300"))


def spread(n: int, n_dsp: int, n_bram: int) -> list:
    """Evenly spread BRAM then DSP columns over n columns (same rule as reference_columns)."""
    cols = [CLB] * n
    if n_bram:
        step = n / n_bram
        for k in range(n_bram):
            cols[min(n - 1, int(k * step))] = BRAM
    if n_dsp:
        free = [i for i in range(n) if cols[i] == CLB]
        step = len(free) / n_dsp
        for k in range(n_dsp):
            cols[free[min(len(free) - 1, int(k * step + step / 2))]] = DSP
    return cols


def block(n: int, n_dsp: int, n_bram: int, where: str) -> list:
    """Hard-block columns packed together: 'center' = one contiguous band in the middle,
    'edges' = half at each edge. DSP and BRAM columns alternate inside the band."""
    hb = []
    d, b = n_dsp, n_bram
    while d or b:
        if b >= d and b:
            hb.append(BRAM); b -= 1
        else:
            hb.append(DSP); d -= 1
    cols = [CLB] * n
    if where == "center":
        start = (n - len(hb)) // 2
        cols[start:start + len(hb)] = hb
    else:
        half = len(hb) // 2
        cols[:half] = hb[:half]
        cols[n - (len(hb) - half):] = hb[half:]
    return cols


def shift(cols: list, k: int) -> list:
    return cols[-k:] + cols[:-k] if k else list(cols)


def named_layout(name: str, cfg: SearchConfig) -> ColumnLayoutSpec:
    """3D hard-block arrangements with the SAME total block counts as the reference
    (2 x per-layer counts); only where the columns sit, and on which layer, changes."""
    n = cfg.width - 2
    _, nd, nb = column_counts(cfg)
    ref = spread(n, nd, nb)
    if name == "aligned":          # reference: identical layers, hard blocks stacked
        return ColumnLayoutSpec([ref, list(ref)])
    if name == "staggered":        # layer 1 shifted by half the hard-block pitch
        pitch = max(1, round(n / max(1, nd + nb)))
        return ColumnLayoutSpec([ref, shift(ref, max(1, pitch // 2))])
    if name == "hb_one_layer":     # all hard blocks on layer 0, layer 1 pure logic
        return ColumnLayoutSpec([spread(n, 2 * nd, 2 * nb), [CLB] * n])
    if name == "split_types":      # DSP on layer 0, BRAM on layer 1
        return ColumnLayoutSpec([spread(n, 2 * nd, 0), spread(n, 0, 2 * nb)])
    if name == "center":           # hard blocks clustered in the middle, both layers
        c = block(n, nd, nb, "center")
        return ColumnLayoutSpec([c, list(c)])
    if name == "edges":            # hard blocks at the left/right edges, both layers
        c = block(n, nd, nb, "edges")
        return ColumnLayoutSpec([c, list(c)])
    if name == "center_edges":     # layer 0 clustered center, layer 1 at edges
        return ColumnLayoutSpec([block(n, nd, nb, "center"), block(n, nd, nb, "edges")])
    raise ValueError(f"unknown layout {name}")


LAYOUTS = ("aligned", "staggered", "hb_one_layer", "split_types", "center", "edges", "center_edges")


def stage(entry: str) -> str:
    suite, name = entry.split("/", 1)
    d = os.path.join(WORK, "bench", name)
    dst = os.path.join(d, name + ".v")
    if not os.path.exists(dst):
        os.makedirs(d, exist_ok=True)
        tmp = f"{dst}.{os.getpid()}.{os.environ.get('TASK_INDEX', '')}.tmp"  # unique: tasks race here
        shutil.copy(os.path.join(ROOT, SUITES[suite], name + ".v"), tmp)
        os.replace(tmp, dst)
    return d


def run(task: dict) -> dict:
    seeds = int(task.get("seeds", 5))
    tdir = "dsp_bram_tall" if TALL else "dsp_bram"
    base = SearchConfig(lazagna_root=ROOT, benchmark_dir=stage(task["design"]), is_verilog=True,
                        channel_width=CW, seeds=seeds, seed_list=tuple(range(1, seeds + 1)),
                        arch_type="combined", search_mode="columns", prep_dir="/prep",
                        fidelity="route", run_tag="x", vpr_jobs=task.get("jobs"),
                        trial_timeout_s=int(task.get("timeout_s", 4 * 3600)),
                        template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
                        template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml")
    cfg, size = autosize(base)
    rec = {"task": task, "sizing": {k: v for k, v in size.items()},
           "cols_per_layer": column_counts(cfg), "seeds": list(cfg.seed_list)}
    tag = task["id"].replace("/", "_").replace(".", "")

    def go(label, spec, arch_type, conn=1.0, vconn=1.0):
        info = {}
        t0 = time.time()
        m, err = _run_one(cfg, spec, f"{tag}{label}", arch_type, conn, 0.739, info=info,
                          fidelity="route", vertical_connectivity=vconn)
        out = {"cpd": m[0] if m else None, "wl": m[1] if m else None, "error": err,
               "per_seed": info.get("per_seed"), "t_s": round(time.time() - t0)}
        if spec is not None:
            out["columns"] = spec.columns
        return out

    kind = task["kind"]
    if kind == "rq1":
        rec["2d"] = go("two", None, "2d")
        rec["3d"] = go("three", reference_columns(cfg), cfg.arch_type)
    elif kind == "layout":
        rec["3d"] = go(task["layout"], named_layout(task["layout"], cfg), cfg.arch_type)
    elif kind == "custom":
        from lazagna_optuna import structured_columns
        if "structured" in task:
            p = task["structured"]
            n = cfg.width - 2
            _, nd, nb = column_counts(cfg)
            spec = structured_columns(n, nd, nb, p["dsp_on_l0"], p["bram_on_l0"], p["cluster"],
                                      p["stagger"], p["band_pos"])
        else:
            spec = ColumnLayoutSpec(task["columns"])
        rec["3d"] = go("cust", spec, cfg.arch_type)
    elif kind == "conn":
        rec["3d"] = go(f"c{task['conn']}v{task.get('vconn', 1)}".replace(".", ""),
                       reference_columns(cfg), cfg.arch_type,
                       conn=float(task["conn"]), vconn=float(task.get("vconn", 1)))
    else:
        raise ValueError(kind)
    return rec


if __name__ == "__main__":
    tasks = [json.loads(l) for l in open(os.environ["TASKS"]) if l.strip()]
    task = tasks[int(os.environ["TASK_INDEX"])]
    out_dir = os.path.join(WORK, "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, task["id"] + ".json")
    if os.path.exists(out) and not os.environ.get("FORCE"):
        print(f"exists, skipping: {out}")
        sys.exit(0)
    t0 = time.time()
    try:
        rec = run(task)
    except Exception as e:
        import traceback
        rec = {"task": task, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
    rec["t_total_s"] = round(time.time() - t0)
    with open(out + ".tmp", "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(out + ".tmp", out)
    print(json.dumps({k: v for k, v in rec.items() if k in ("task", "error", "t_total_s")}))
    for k in ("2d", "3d"):
        if k in rec:
            print(k, rec[k]["cpd"], rec[k]["wl"], rec[k]["error"])
