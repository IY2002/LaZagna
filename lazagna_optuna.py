from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import glob
import math
import os

import optuna

from lazagna_arch_model import (
    ExperimentOptions, GridOptions, BenchmarkOptions, PlacementOptions,
    SeedOptions, SwitchBlock3DOptions, InterlayerDelayOptions, AdvancedOptions, run_lazagna,
)
from layout_space import LayoutSpec, ColumnLayoutSpec, NAMED_LAYOUTS, CLB, DSP, BRAM, IO
from arch_from_template import render_arch_from_template, tile_heights

def build_architecture(spec: LayoutSpec, width: int, height: int, template_path: str,
                       layers: int = 2) -> str:
    """layers=1 for the 2D baseline: the 2D template has a single die, and writing a two-layer
    layout into it gave two dies with no vertical routing between them (unroutable)."""
    return render_arch_from_template(template_path, spec, width, height, layers=layers)


import re as _re

_CPD_RE = _re.compile(r"Final critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
_WL_RE = _re.compile(r"Total wirelength:\s*([\d]+)")

def parse_results(results_dir: str, only_containing: Optional[str] = None) -> Optional[tuple[float, float]]:
    """Read real CPD (seconds) and WL from VPR's own logs under tasks_run/.

    LaZagna runs each benchmark into tasks_run/<run-folder>/.../Common/vpr_stdout.log
    and that log holds the true 'Final critical path delay' and 'Total wirelength'.
    The results/ summary CSV is unreliable (often zero-filled), so we go to source.

    `only_containing` filters run folders by experiment name so we score exactly the
    run we just launched. lazagna_root is inferred from results_dir's parent.
    """
    lazagna_root = os.path.dirname(results_dir.rstrip("/"))
    tasks_run = os.path.join(lazagna_root, "tasks_run")
    logs = glob.glob(os.path.join(tasks_run, "**", "vpr_stdout.log"), recursive=True)
    if only_containing:

        def _exp_matches(logpath: str) -> bool:
            folder = os.path.basename(logpath.split("/task_")[0])
            if "_vp_" not in folder:
                return False
            before = folder.split("_vp_")[0]
            return only_containing in before.split("_")
        matched = [l for l in logs if _exp_matches(l)]
        if not matched:
            return None
        logs = matched
    if not logs:
        return None

    cpds: list[float] = []
    wls: list[float] = []
    seen_folders = set()
    for path in logs:
        folder = path.split("/task_")[0]
        if folder in seen_folders:
            continue
        seen_folders.add(folder)
        try:
            text = open(path, errors="ignore").read()
        except OSError:
            continue
        if "VPR succeeded" not in text:
            continue
        m_cpd = _CPD_RE.search(text)
        m_wl = _WL_RE.search(text)
        if m_cpd:
            cpds.append(float(m_cpd.group(1)) * 1e-9)
        if m_wl:
            wls.append(float(m_wl.group(1)))
    if not cpds or not wls:
        return None
    return _geomean(cpds), _geomean(wls)

def _geomean(xs: list[float]) -> float:
    xs = [x for x in xs if x > 0]
    if not xs:
        return float("inf")
    return math.exp(sum(math.log(x) for x in xs) / len(xs))

@dataclass
class SearchConfig:
    """Everything the study needs that isn't a tuned hyperparameter."""
    lazagna_root: str
    benchmark_dir: str
    is_verilog: bool = False
    width: int = 12
    height: int = 12
    width_2d: int = 17
    height_2d: int = 17
    channel_width: int = 300
    seeds: int = 1
    # Explicit placement seeds. Empty means 1..seeds. The SAME seeds are used for every trial
    # and the reference, so comparisons are paired. The old behaviour drew fresh random seeds
    # per run, which put seed noise (~1.5% CPD on clma) into every trial-vs-reference delta.
    seed_list: tuple[int, ...] = ()
    arch_type: str = "3d_sb"
    search_mode: str = "layout"
    sampler: str = "tpe"
    parallel: bool = False

    run_tag: str = field(default_factory=lambda: "run" + str(int(__import__("time").time())))

    # STATIC repo templates only. The old default pointed at a delay-ratio-generated file
    # (arch_files/vtr_3d_cb_arch_dsp_bram_10x10_delay_ratio_0.739.xml) that only exists after
    # a prior flow run -- in a fresh container it is missing (PACE run 11659291, phase 1
    # FileNotFoundError). The flow re-derives interlayer delays from the yaml delay_ratio at
    # run time, so the raw template is the correct input.
    template_path: str = "arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml"
    template_2d_path: str = "arch_files/templates/dsp_bram/vtr_2d_arch_dsp_bram.xml"
    # Hard cap per flow invocation; a hung yosys/VPR otherwise pins a worker until wall-time.
    trial_timeout_s: int = 7200

    # Fast path (lazagna_fastflow): synthesize + pack once per benchmark, then run VPR directly
    # per trial. False falls back to the full LaZagna flow (still VPR-only, no bitstream).
    fast_flow: bool = True
    # "place" = placement estimates (cheap search objective), "route" = post-route metrics.
    fidelity: str = "route"
    # Shared cache for the one-time BLIF/.net; put it on storage all workers can see.
    prep_dir: str = ""
    # Timeout for the one-time synthesis + pack (large Koios designs synthesize for an hour+).
    prep_timeout_s: int = 6 * 3600
    # autosize(): the 2D device is the smallest grid where every block type is at most this
    # utilized; the 3D device matches the 2D device's total tile count over two layers.
    target_util: float = 0.8

    hb_period_choices: tuple[int, ...] = (4, 6, 8, 12)
    edge_fraction_range: tuple[float, float] = (0.1, 0.35)
    delay_ratio_range: tuple[float, float] = (0.4, 1.2)
    connectivity_choices: tuple[float, ...] = (0.33, 0.66, 1.0)
    column_block_choices: tuple[str, ...] = (CLB, DSP, BRAM)
    # Column composition is FIXED per trial (agreed with Ismael, 2026-08-22): every trial
    # gets identical block counts and only the arrangement varies, so RQ2 measures placement
    # quality rather than resource composition. Order: (CLB, DSP, BRAM). 12.5/12.5/75 is the
    # convention from prior work and is held CONSTANT across benchmarks (Ismael, 2026-09-08:
    # tuning the ratio to a single benchmark is not a useful architecture). Per-workload ratio
    # optimization is a possible future direction, not something to vary per run here.
    block_ratios: tuple[float, float, float] = (0.75, 0.125, 0.125)
    clb_col_fraction: float = 0.68   # legacy, only used if fixed_block_counts=False
    dsp_col_fraction: float = 0.10   # legacy
    fixed_block_counts: bool = True
    type_sb_choices: tuple[str, ...] = ("3d_sb",)
    connection_type_choices: tuple[str, ...] = ("subset",)
    fine_connectivity_choices: tuple[float, ...] = (0.1, 0.2, 0.33, 0.5, 0.66, 0.8, 1.0)

def sample_layout(trial: optuna.Trial, cfg: SearchConfig) -> LayoutSpec:
    family = trial.suggest_categorical("family", ["distributed", "edge"])
    asymmetry = trial.suggest_float("asymmetry", 0.0, 1.0)
    separate = trial.suggest_categorical("separate_dsp_bram", [False, True])
    if family == "distributed":
        period = trial.suggest_categorical("hb_period", list(cfg.hb_period_choices))
        return LayoutSpec(family=family, hb_period=period, asymmetry=asymmetry, separate_dsp_bram=separate)
    frac = trial.suggest_float("edge_fraction", *cfg.edge_fraction_range)
    return LayoutSpec(family=family, edge_fraction=frac, asymmetry=asymmetry, separate_dsp_bram=separate)


def seed_values(cfg: SearchConfig) -> tuple[int, ...]:
    return tuple(cfg.seed_list) if cfg.seed_list else tuple(range(1, cfg.seeds + 1))


def column_counts(cfg: SearchConfig, n: Optional[int] = None) -> tuple[int, int, int]:
    """Exact per-layer column counts (CLB, DSP, BRAM) from cfg.block_ratios for n interior
    columns (default: the 3D device). BRAM and DSP are rounded, CLB absorbs the remainder."""
    n = cfg.width - 2 if n is None else n
    _, dsp_f, bram_f = cfg.block_ratios
    n_dsp = int(round(dsp_f * n))
    n_bram = int(round(bram_f * n))
    return n - n_dsp - n_bram, n_dsp, n_bram


def sample_columns(trial: optuna.Trial, cfg: SearchConfig) -> ColumnLayoutSpec:
    """Sample an ARRANGEMENT of a fixed multiset of columns.

    Each column gets a continuous key; the highest-ranked keys become BRAM, the next
    become DSP, the rest CLB. That guarantees every trial has identical block counts
    (so a win cannot come from extra hard blocks) while keeping the same dimensionality
    and a smooth space for TPE. Set fixed_block_counts=False for the old independent
    per-column sampling, which let DSP columns vary roughly 1 to 6 between trials."""
    n = cfg.width - 2
    if not cfg.fixed_block_counts:
        dsp_hi = cfg.clb_col_fraction + cfg.dsp_col_fraction
        cols = []
        for layer in range(2):
            layer_cols = []
            for i in range(n):
                r = trial.suggest_float(f"L{layer}c{i}", 0.0, 1.0)
                layer_cols.append(CLB if r < cfg.clb_col_fraction else (DSP if r < dsp_hi else BRAM))
            cols.append(layer_cols)
        return ColumnLayoutSpec(columns=cols)

    _, n_dsp, n_bram = column_counts(cfg)
    cols = []
    for layer in range(2):
        keys = [(trial.suggest_float(f"L{layer}c{i}", 0.0, 1.0), i) for i in range(n)]
        order = [i for _, i in sorted(keys, reverse=True)]
        layer_cols = [CLB] * n
        for i in order[:n_bram]:
            layer_cols[i] = BRAM
        for i in order[n_bram:n_bram + n_dsp]:
            layer_cols[i] = DSP
        cols.append(layer_cols)
    return ColumnLayoutSpec(columns=cols)


def sample_connectivity(trial: optuna.Trial, cfg: SearchConfig):
    type_sb = trial.suggest_categorical("type_sb", list(cfg.type_sb_choices))
    if type_sb in ("2d", "3d_cb", "3d_cb_out_only"):
        connectivity = 1.0
        connection_type = "subset"
    else:
        connectivity = trial.suggest_categorical("connectivity", list(cfg.fine_connectivity_choices))
        connection_type = trial.suggest_categorical("connection_type", list(cfg.connection_type_choices)) \
            if len(cfg.connection_type_choices) > 1 else cfg.connection_type_choices[0]
    delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)
    return type_sb, connectivity, connection_type, delay_ratio

def _experiment_options(cfg: SearchConfig, exp_name: str, arch_type: str, connectivity: float,
                        delay_ratio: float, connection_type: str = "subset") -> ExperimentOptions:
    opts = ExperimentOptions(
        experiment_name=exp_name,
        grid=GridOptions(width_3d=cfg.width, height_3d=cfg.height,
                         width_2d=cfg.width_2d, height_2d=cfg.height_2d,
                         channel_width=cfg.channel_width),
        benchmarks=BenchmarkOptions(directory=cfg.benchmark_dir, is_verilog=cfg.is_verilog),
        placement=PlacementOptions(algorithm=["cube_bb"]),
        seeds=SeedOptions.from_list(seed_values(cfg)),
        switch_block_3d=SwitchBlock3DOptions(connectivity=[connectivity],
                                             connection_type=[connection_type]),
        interlayer_delay=InterlayerDelayOptions(delay_ratio=[delay_ratio]),
        advanced=AdvancedOptions(vpr_only=True),
    )
    opts.architectures[0].type = arch_type
    return opts


def _template(cfg: SearchConfig, is_2d: bool) -> str:
    tpl = cfg.template_2d_path if is_2d else cfg.template_path
    return tpl if os.path.isabs(tpl) else os.path.join(cfg.lazagna_root, tpl)


def prepare(cfg: SearchConfig) -> dict:
    """One-time synthesis + pack for cfg's benchmark: {"blif", "net", "demand", ...}.
    Every worker calls this; only the first does the work (lazagna_fastflow handles locking)."""
    from lazagna_fastflow import prepare_benchmark, block_signature
    tpl2d, tpl3d = open(_template(cfg, True)).read(), open(_template(cfg, False)).read()
    if block_signature(tpl2d) != block_signature(tpl3d):
        raise ValueError("2D and 3D templates define different blocks; one packing cannot serve both")
    opts = _experiment_options(cfg, "prep", "2d", 1.0, 0.739)
    prep_dir = cfg.prep_dir or os.path.join(cfg.lazagna_root, "prep_cache")
    return prepare_benchmark(tpl2d, opts, prep_dir, cfg.lazagna_root, timeout_s=cfg.prep_timeout_s)


def _capacity(cfg: SearchConfig, n: int, h: int, heights: dict, layers: int = 1) -> dict:
    """Blocks of each type on a device with n interior columns x h interior rows per layer."""
    n_clb, n_dsp, n_bram = column_counts(cfg, n)
    return {"clb": layers * n_clb * h,
            "complex_dsp": layers * n_dsp * (h // heights.get("complex_dsp", 1)),
            "spram": layers * n_bram * (h // heights.get("spram", 1)),
            "io": layers * 2 * (n + h) * 8}      # io capacity 8 per perimeter tile


def size_devices(cfg: SearchConfig, demand: dict, target_util: Optional[float] = None) -> dict:
    """2D sets the size. The 2D device is the smallest near-square grid (aspect 0.8-1.25)
    where every block type is at most target_util utilized. The 3D device then has two
    layers whose total tile count is as close as possible to the 2D device's, among grids
    that also fit the design. Interior heights are multiples of the hard-block heights' LCM,
    so tall DSP/BRAM columns tile exactly with no leftover rows."""
    import math as _m
    u = target_util or cfg.target_util
    heights = tile_heights(open(_template(cfg, True)).read())
    q = _m.lcm(heights.get("complex_dsp", 1), heights.get("spram", 1))
    need = {t: demand.get(t, 0) / u for t in ("clb", "complex_dsp", "spram")}
    need["io"] = demand.get("io", 0)

    def fits(cap):
        return all(cap[t] >= need[t] for t in need)

    def candidates(layers):
        for h in range(q, 2000, q):
            for n in range(max(4, int(0.8 * h)), int(1.25 * h) + 2):
                yield n, h, _capacity(cfg, n, h, heights, layers)

    best2d = None
    for n, h, cap in candidates(1):
        if fits(cap) and (best2d is None or n * h < best2d[0] * best2d[1]):
            best2d = (n, h, cap)
        if best2d and h > 1.6 * best2d[1]:
            break
    if best2d is None:
        raise ValueError(f"no 2D device fits demand {demand}")
    n2, h2, cap2 = best2d
    target = n2 * h2

    best3d = None
    for n, h, cap in candidates(2):
        if 2 * n * h > 1.5 * target:
            if h * h > target:
                break
            continue
        if fits(cap):
            key = (abs(2 * n * h - target), abs(n - h))
            if best3d is None or key < best3d[0]:
                best3d = (key, n, h, cap)
    if best3d is None:
        # Tiny or IO-bound designs: the row quantum (LCM of block heights) makes every
        # 3D grid much larger than the 2D one. Take the smallest 3D grid that fits.
        for n, h, cap in candidates(2):
            if fits(cap) and (best3d is None or n * h < best3d[1] * best3d[2]):
                best3d = ((abs(2 * n * h - target), abs(n - h)), n, h, cap)
            if best3d and h > 1.6 * best3d[2]:
                break
    if best3d is None:
        raise ValueError(f"no 3D device fits demand {demand}")
    _, n3, h3, cap3 = best3d
    return {"width_2d": n2 + 2, "height_2d": h2 + 2, "width": n3 + 2, "height": h3 + 2,
            "tiles_2d": n2 * h2, "tiles_3d": 2 * n3 * h3, "cap_2d": cap2, "cap_3d": cap3,
            "demand": demand, "target_util": u}


def autosize(cfg: SearchConfig) -> tuple[SearchConfig, dict]:
    """Prepare cfg's benchmark and return (cfg sized to its measured block demand, sizing info)."""
    import dataclasses
    meta = prepare(cfg)
    info = size_devices(cfg, meta["demand"])
    sized = dataclasses.replace(cfg, width=info["width"], height=info["height"],
                                width_2d=info["width_2d"], height_2d=info["height_2d"])
    return sized, info


def _run_one(cfg: SearchConfig, spec_or_none, exp_name: str, arch_type: str,
             connectivity: float, delay_ratio: float, connection_type: str = "subset",
             info: Optional[dict] = None, fidelity: Optional[str] = None):
    """Run one architecture over all seeds. Returns ((cpd, wl), None) or (None, error).
    `info`, if given, is filled with per-seed details (placement estimates and routed values)."""
    is_2d = arch_type == "2d"
    if spec_or_none is None:
        # Default: the resource-matched evenly spread reference, sized for this device.
        spec_or_none = reference_columns(cfg, (cfg.width_2d if is_2d else cfg.width) - 2)
    spec = spec_or_none
    arch_w = cfg.width_2d if is_2d else cfg.width
    arch_h = cfg.height_2d if is_2d else cfg.height
    arch = build_architecture(spec, arch_w, arch_h, _template(cfg, is_2d), layers=1 if is_2d else 2)
    opts = _experiment_options(cfg, exp_name, arch_type, connectivity, delay_ratio, connection_type)

    if cfg.fast_flow:
        from lazagna_fastflow import evaluate
        try:
            meta = prepare(cfg)
            res = evaluate(arch, opts, meta["blif"], meta["net"], seed_values(cfg),
                           stage=fidelity or cfg.fidelity,
                           lazagna_root=cfg.lazagna_root, timeout_s=cfg.trial_timeout_s)
        except Exception as e:   # setup/prepare failures become a pruned trial, not a dead worker
            return None, f"{type(e).__name__}: {e}"
        if info is not None:
            info.update(res)
        if not res["ok"]:
            return None, res["error"]
        return (res["cpd"], res["wl"]), None

    result = run_lazagna(arch, opts, lazagna_root=cfg.lazagna_root,
                         timeout_s=cfg.trial_timeout_s)
    if result["returncode"] != 0:
        return None, result["stderr"][-1500:]

    metrics = parse_results(os.path.join(cfg.lazagna_root, "results"), only_containing=exp_name)
    return metrics, None

def reference_columns(cfg: SearchConfig, n: Optional[int] = None) -> ColumnLayoutSpec:
    """Reference layout with the SAME block counts as every sampled trial (evenly spread),
    so the reference is resource-matched to the search and the comparison is placement-only.
    n = interior columns (default: the 3D device; pass width_2d - 2 for the 2D baseline)."""
    n = cfg.width - 2 if n is None else n
    _, n_dsp, n_bram = column_counts(cfg, n)
    pattern = [CLB] * n
    if n_bram:
        step = n / n_bram
        for k in range(n_bram):
            pattern[min(n - 1, int(k * step))] = BRAM
    if n_dsp:
        free = [i for i in range(n) if pattern[i] == CLB]
        step = len(free) / n_dsp if n_dsp else 1
        for k in range(n_dsp):
            pattern[free[min(len(free) - 1, int(k * step + step / 2))]] = DSP
    return ColumnLayoutSpec(columns=[list(pattern), list(pattern)])


def baseline_signature(cfg: SearchConfig) -> str:
    """Identifies a reference run. Excludes the sampler, so the TPE / NSGA-II / random studies
    SHARE one reference instead of each computing its own. In the 2026-08-14 campaign they each
    ran a separate reference (9.822 / 9.874 / 9.977 ns), which made the per-study "% vs
    reference" numbers non-comparable across samplers."""
    import hashlib
    key = "|".join(str(x) for x in (
        os.path.basename(cfg.benchmark_dir.rstrip("/")), cfg.is_verilog,
        cfg.width, cfg.height, cfg.channel_width, cfg.arch_type, seed_values(cfg),
        cfg.search_mode, cfg.block_ratios, cfg.fixed_block_counts, cfg.template_path,
        cfg.fast_flow, cfg.fidelity,
    ))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _read_baseline(path: str):
    import json
    try:
        with open(path) as f:
            d = json.load(f)
        if d.get("cpd") and d.get("wl"):
            return d["cpd"], d["wl"]
    except (OSError, ValueError):
        pass
    return None


def _write_baseline(path: str, cpd: float, wl: float) -> None:
    import json
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump({"cpd": cpd, "wl": wl}, f)
    os.replace(tmp, path)   # atomic, so a concurrent reader never sees a partial file


def make_objective(cfg: SearchConfig, block_types=None, study: Optional[optuna.Study] = None,
                   shared_baseline_path: Optional[str] = None):
    """When `study` is given (parallel workers sharing storage), the reference baseline is
    computed ONCE and shared through study user attrs: the first worker to arrive claims it
    (claim -> re-read guard), the rest poll. Without `study`, behaves as before (per-process)."""

    baseline = {"cpd": None, "wl": None}

    def _compute_baseline():
        metrics, err = _run_one(cfg, reference_columns(cfg), f"{cfg.run_tag}ref", cfg.arch_type, 1.0, 0.739)
        if metrics is None:
            raise RuntimeError(f"3D-aligned reference baseline run failed: {err}")
        return metrics

    def ensure_baseline():
        import time as _t
        if baseline["cpd"] is not None:
            return
        # Shared-file path: every study using the same benchmark/grid/ratios reuses ONE
        # reference run, so cross-sampler comparisons are against a common denominator.
        if shared_baseline_path:
            got = _read_baseline(shared_baseline_path)
            if got is None:
                lock = shared_baseline_path + ".lock"
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    owner = True
                except FileExistsError:
                    owner = False
                if owner:
                    cpd, wl = _compute_baseline()
                    _write_baseline(shared_baseline_path, cpd, wl)
                    got = (cpd, wl)
                else:
                    for _ in range(180):        # reference run is ~10-20 min
                        _t.sleep(20)
                        got = _read_baseline(shared_baseline_path)
                        if got:
                            break
                    if got is None:             # owner died holding the lock
                        cpd, wl = _compute_baseline()
                        _write_baseline(shared_baseline_path, cpd, wl)
                        got = (cpd, wl)
            baseline["cpd"], baseline["wl"] = got
            if study is not None and study.user_attrs.get("baseline_cpd") is None:
                study.set_user_attr("baseline_cpd", got[0])
                study.set_user_attr("baseline_wl", got[1])
            return
        if study is None:
            baseline["cpd"], baseline["wl"] = _compute_baseline()
            return
        # shared-storage path
        attrs = study.user_attrs
        if attrs.get("baseline_cpd") is not None:
            baseline["cpd"], baseline["wl"] = attrs["baseline_cpd"], attrs["baseline_wl"]
            return
        my_tag = f"{cfg.run_tag}-{os.getpid()}"
        if attrs.get("baseline_claim") is None:
            study.set_user_attr("baseline_claim", my_tag)
            _t.sleep(5)  # let a racing claim overwrite before we re-read
        if study.user_attrs.get("baseline_claim") == my_tag:
            cpd, wl = _compute_baseline()
            study.set_user_attr("baseline_cpd", cpd)
            study.set_user_attr("baseline_wl", wl)
            baseline["cpd"], baseline["wl"] = cpd, wl
            return
        # another worker owns the claim: poll (baseline run is ~10-20 min); failsafe = compute anyway
        for _ in range(90):
            _t.sleep(60)
            attrs = study.user_attrs
            if attrs.get("baseline_cpd") is not None:
                baseline["cpd"], baseline["wl"] = attrs["baseline_cpd"], attrs["baseline_wl"]
                return
        cpd, wl = _compute_baseline()
        study.set_user_attr("baseline_cpd", cpd)
        study.set_user_attr("baseline_wl", wl)
        baseline["cpd"], baseline["wl"] = cpd, wl

    def objective(trial: optuna.Trial) -> tuple[float, float]:
        ensure_baseline()
        if cfg.search_mode == "connectivity":
            spec = NAMED_LAYOUTS["aligned"]
            arch_type, connectivity, connection_type, delay_ratio = sample_connectivity(trial, cfg)
        elif cfg.search_mode == "columns":
            spec = sample_columns(trial, cfg)
            arch_type = cfg.arch_type
            connectivity = trial.suggest_categorical("connectivity", list(cfg.connectivity_choices))
            connection_type = "subset"
            delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)
        else:
            spec = sample_layout(trial, cfg)
            arch_type = cfg.arch_type
            connectivity = trial.suggest_categorical("connectivity", list(cfg.connectivity_choices))
            connection_type = "subset"
            delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)

        metrics, err = _run_one(cfg, spec, f"{cfg.run_tag}t{trial.number}",
                                arch_type, connectivity, delay_ratio, connection_type)
        if metrics is None:
            trial.set_user_attr("stderr_tail", err or "parse_failed")
            raise optuna.TrialPruned()

        cpd, wl = metrics

        cpd_impr = 100.0 * (baseline["cpd"] - cpd) / baseline["cpd"]
        wl_impr = 100.0 * (baseline["wl"] - wl) / baseline["wl"]
        trial.set_user_attr("cpd_raw", cpd)
        trial.set_user_attr("wl_raw", wl)
        trial.set_user_attr("cpd_impr_pct", cpd_impr)
        trial.set_user_attr("wl_impr_pct", wl_impr)
        trial.set_user_attr("baseline_cpd", baseline["cpd"])
        trial.set_user_attr("baseline_wl", baseline["wl"])

        return -cpd_impr, -wl_impr

    return objective

def _make_sampler(cfg: SearchConfig):
    if cfg.sampler == "nsga2":
        return optuna.samplers.NSGAIISampler()
    if cfg.sampler == "random":
        return optuna.samplers.RandomSampler()
    return optuna.samplers.TPESampler(constant_liar=cfg.parallel)


def journal_storage(path: str):
    """Optuna storage that is safe on NFS/Lustre and for many parallel workers.
    sqlite is neither (PACE run 11659291 died with 'sqlite3.OperationalError: disk I/O
    error'); optuna's docs point to JournalStorage for exactly this case."""
    from optuna.storages import JournalStorage
    try:  # optuna >= 4
        from optuna.storages.journal import JournalFileBackend
        return JournalStorage(JournalFileBackend(path))
    except ImportError:  # optuna 3.x name
        from optuna.storages import JournalFileStorage
        return JournalStorage(JournalFileStorage(path))


def run_study(cfg: SearchConfig, n_trials: int = 40, seed_named: bool = True,
              study_name: str = "lazagna_3d", storage=None) -> optuna.Study:
    """`storage` may be an optuna storage URL string OR a storage object
    (e.g. journal_storage(...) for parallel/Lustre runs)."""
    study = optuna.create_study(
        directions=["minimize", "minimize"],
        study_name=study_name,
        storage=storage,
        load_if_exists=storage is not None,
        sampler=_make_sampler(cfg),
    )

    if seed_named and cfg.search_mode == "layout":

        for name, spec in NAMED_LAYOUTS.items():
            params = {
                "family": spec.family,
                "asymmetry": spec.asymmetry,
                "separate_dsp_bram": spec.separate_dsp_bram,
                "connectivity": 1.0,
                "delay_ratio": 0.739,
            }
            if spec.family == "distributed":
                params["hb_period"] = spec.hb_period if spec.hb_period in cfg.hb_period_choices else 8
            else:
                params["edge_fraction"] = min(max(spec.edge_fraction, cfg.edge_fraction_range[0]),
                                              cfg.edge_fraction_range[1])
            study.enqueue_trial(params, user_attrs={"seeded_from": name})

    study.optimize(make_objective(cfg, study=study), n_trials=n_trials)
    return study

def report(study: optuna.Study) -> None:

    base_cpd = base_wl = None
    for t in study.trials:
        if t.user_attrs.get("baseline_cpd"):
            base_cpd = t.user_attrs["baseline_cpd"]
            base_wl = t.user_attrs["baseline_wl"]
            break

    print(f"\nfinished {len(study.trials)} trials")
    if base_cpd:
        print(f"2D baseline: CPD={base_cpd:.4e}  WL={base_wl:.1f}")
    print("\nPareto-optimal 3D configurations (improvement over 2D, higher = better):")

    best = sorted(study.best_trials,
                  key=lambda t: t.user_attrs.get("cpd_impr_pct", -999), reverse=True)
    for t in best:
        cpd_i = t.user_attrs.get("cpd_impr_pct")
        wl_i = t.user_attrs.get("wl_impr_pct")
        seeded = t.user_attrs.get("seeded_from", "")
        tag = f"  [from {seeded}]" if seeded else ""
        if cpd_i is not None:
            print(f"  trial {t.number}: CPD {cpd_i:+.2f}%  WL {wl_i:+.2f}%{tag}")
        else:
            print(f"  trial {t.number}: (pruned/no metrics){tag}")
        print(f"      params: {t.params}")

    scored = [t for t in study.trials if t.user_attrs.get("cpd_impr_pct") is not None]
    if scored:
        top = max(scored, key=lambda t: t.user_attrs["cpd_impr_pct"])
        print(f"\nBest CPD improvement overall: trial {top.number}, "
              f"{top.user_attrs['cpd_impr_pct']:+.2f}% vs 2D")
        print(f"  params: {top.params}")
        seeded_top = max((t for t in scored if t.user_attrs.get("seeded_from")),
                         key=lambda t: t.user_attrs["cpd_impr_pct"], default=None)
        if seeded_top and seeded_top.number != top.number:
            print(f"  best paper layout: {seeded_top.user_attrs['seeded_from']} "
                  f"at {seeded_top.user_attrs['cpd_impr_pct']:+.2f}% "
                  f"-- optimizer beat it by "
                  f"{top.user_attrs['cpd_impr_pct'] - seeded_top.user_attrs['cpd_impr_pct']:.2f} pts")

if __name__ == "__main__":
    cfg = SearchConfig(
        lazagna_root=os.environ.get("LAZAGNA_ROOT", os.path.expanduser("~/LaZagna")),
        benchmark_dir="{lazagna_root}/benchmarks/MCNC_benchmarks/clma",
        is_verilog=False,
        width=30, height=30, width_2d=42, height_2d=42,
        channel_width=100, seeds=3,
        search_mode="connectivity",
    )
    study = run_study(cfg, n_trials=15, study_name="lazagna_clma_conn",
                      storage="sqlite:///lazagna_clma_conn.db")
    report(study)
