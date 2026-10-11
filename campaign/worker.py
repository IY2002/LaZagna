# Campaign worker — one instance per SLURM array task. All workers share the optuna studies
# through JournalStorage files on the host work dir (/work/journal), so N workers = N trials
# in flight with no sqlite and no shared-writable overlay (both failed on PACE run 11659291:
# 'sqlite3.OperationalError: disk I/O error' + 50 GB overlay filled -> ENOSPC).
#
# Each worker loops over the study queue in order and contributes single trials until a study
# reaches its target trial count, then moves on. TPE runs with constant_liar=True so parallel
# workers do not pile onto the same point. The reference-baseline run is computed once per
# study (first worker claims it via study user attrs; the rest poll — see make_objective).
#
# Columns study (fast flow): the design is synthesized + packed once (shared /prep cache),
# both devices are sized to its measured demand (2D sets the size, 3D matches the tile
# count), every trial uses the same placement seeds, and the search objective is VPR's
# PLACEMENT estimate (FIDELITY=place), which skips routing. The "promote" study then routes
# the candidates that matter: the Pareto set, the top PROMOTE_TOP trials, PROMOTE_RANDOM
# random trials (to measure how well the placement estimate ranks layouts), the 3D
# reference, and the 2D baseline. Results land in /work/promote/<study>/*.json.
#
# env: WORKER_ID, WORK (default /work), LAZAGNA_ROOT (default /opt/LaZagna),
#      LAZAGNA_CODE (host code dir, default LAZAGNA_ROOT), SEEDS (3), TRIALS_COLUMNS (35),
#      TRIALS_SAMPLER (15), STUDIES (default "columns promote tpe nsga2 random"),
#      COLUMNS_DESIGN ("koios/eltwise_layer"), FIDELITY ("place"), TALL (1), TARGET_UTIL (0.8),
#      PROMOTE_TOP (10), PROMOTE_RANDOM (10), KEEP_RRG (unset -> per-trial RRG cleanup on)
import os
import shutil
import sys
import time

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
WORKER_ID = int(os.environ.get("WORKER_ID", os.environ.get("SLURM_ARRAY_TASK_ID", "0")))
SEEDS = int(os.environ.get("SEEDS", "3"))
# Fixed channel width for every study. Overridable but 300 is the lab standard.
CW = int(os.environ.get("CW", "300"))
TRIALS_COLUMNS = int(os.environ.get("TRIALS_COLUMNS", "35"))
TRIALS_SAMPLER = int(os.environ.get("TRIALS_SAMPLER", "15"))
# Accept space- or comma-separated (commas survive sbatch --export unmangled).
import re as _re
STUDIES = [s for s in _re.split(r"[,\s]+", os.environ.get("STUDIES", "columns promote tpe nsga2 random")) if s]
COLUMNS_DESIGN = os.environ.get("COLUMNS_DESIGN", "koios/eltwise_layer")
FIDELITY = os.environ.get("FIDELITY", "place")
TALL = os.environ.get("TALL", "1") != "0"
TARGET_UTIL = float(os.environ.get("TARGET_UTIL", "0.8"))
PROMOTE_TOP = int(os.environ.get("PROMOTE_TOP", "10"))
PROMOTE_RANDOM = int(os.environ.get("PROMOTE_RANDOM", "10"))
# Same seeds for every trial, reference and baseline: paired comparisons.
SEED_LIST = tuple(range(1, SEEDS + 1))
KEEP_RRG = bool(os.environ.get("KEEP_RRG"))
# Batch width = how many workers run this study concurrently. Each width gets its own
# study so the RQ3 ablation (1, 10, 25, 50, 100) can be compared. Set by submit_campaign.sh.
BATCH = os.environ.get("BATCH", "")
SUFFIX = f"_b{BATCH}" if BATCH else ""

os.chdir(ROOT)
sys.path[:0] = [CODE, ROOT]   # host code first (see campaign/binds.sh)

import json
import random
import optuna
from lazagna_optuna import (SearchConfig, make_objective, _make_sampler, journal_storage,
                            baseline_signature, column_counts, autosize, sample_columns,
                            reference_columns, _run_one)

# Stale-image guard: these features live inside the image (/opt/LaZagna). If Ismael reuses an
# old lazagna.sif, fail loud instead of crashing cryptically mid-run.
import inspect
if "study" not in inspect.signature(make_objective).parameters:
    sys.exit("IMAGE STALE: /opt/LaZagna in this .sif predates the parallel-campaign update. "
             "Delete lazagna.sif and resubmit (submit_campaign.sh rebuilds it).")

optuna.logging.set_verbosity(optuna.logging.WARNING)


def ensure_bench(name: str, src_rel: str) -> str:
    """Single-design benchmark dir on the HOST work dir (container benchmarks/ is read-only)."""
    bdir = os.path.join(WORK, "bench", name)
    dst = os.path.join(bdir, os.path.basename(src_rel))
    if not os.path.exists(dst):
        os.makedirs(bdir, exist_ok=True)
        src = os.path.join(ROOT, src_rel)
        if not os.path.exists(src):
            sys.exit(f"FATAL: benchmark source missing: {src}")
        tmp = dst + f".w{WORKER_ID}.tmp"
        shutil.copy(src, tmp)
        os.replace(tmp, dst)  # atomic vs racing workers
    return bdir


SUITES = {"koios": "benchmarks/koios", "vtr": "benchmarks/VTR_benchmarks"}
_COLUMNS = {}


def columns_cfg() -> SearchConfig:
    """Columns-study config, sized to COLUMNS_DESIGN's measured demand (cached per process).
    The first call may block while one worker synthesizes + packs the design."""
    if "cfg" in _COLUMNS:
        return _COLUMNS["cfg"]
    suite, name = COLUMNS_DESIGN.split("/", 1)
    tdir = "dsp_bram_tall" if TALL else "dsp_bram"
    base = SearchConfig(
        lazagna_root=ROOT,
        benchmark_dir=ensure_bench("cols_" + name, f"{SUITES[suite]}/{name}.v"),
        is_verilog=True,
        # cw 300 everywhere: the lab has used 300 in all prior work, so results stay
        # comparable. CW is pinned on the vpr line, so VTR never runs its own search.
        channel_width=CW, seeds=SEEDS, seed_list=SEED_LIST,
        arch_type="combined", search_mode="columns",
        template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
        template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml",
        connectivity_choices=(1.0,),
        delay_ratio_range=(0.739, 0.739),
        parallel=True,
        fidelity=FIDELITY, prep_dir="/prep", target_util=TARGET_UTIL,
        run_tag="cols",
    )
    cfg, info = autosize(base)
    print(f"[w{WORKER_ID}] {COLUMNS_DESIGN}: demand {info['demand']} -> 2D "
          f"{info['width_2d']}x{info['height_2d']} ({info['tiles_2d']} tiles), 3D 2x"
          f"{info['width']}x{info['height']} ({info['tiles_3d']} tiles), "
          f"cols/layer CLB/DSP/BRAM={column_counts(cfg)}", flush=True)
    _COLUMNS["cfg"] = cfg
    return cfg


def columns_study_name() -> str:
    name = COLUMNS_DESIGN.split("/", 1)[1].replace(".", "_")
    return f"columns_{name}_{'tall' if TALL else '1x1'}_{FIDELITY}" + SUFFIX


def sampler_cfg(sampler: str) -> SearchConfig:
    return SearchConfig(
        lazagna_root=ROOT,
        benchmark_dir=os.path.join(ROOT, "benchmarks", "MCNC_benchmarks", "clma"),
        is_verilog=False,
        width=30, height=30, width_2d=42, height_2d=42,
        channel_width=CW, seeds=SEEDS, seed_list=SEED_LIST,
        arch_type="3d_sb", search_mode="connectivity", prep_dir="/prep",
        type_sb_choices=("3d_sb",),
        sampler=sampler, parallel=True,
        run_tag=f"smp{sampler}",
    )


STUDY_DEFS = {
    "columns": dict(cfg=columns_cfg, target=TRIALS_COLUMNS, study=None),   # name: columns_study_name()
    "tpe":     dict(cfg=lambda: sampler_cfg("tpe"),    target=TRIALS_SAMPLER, study="clma_sampler_tpe" + SUFFIX),
    "nsga2":   dict(cfg=lambda: sampler_cfg("nsga2"),  target=TRIALS_SAMPLER, study="clma_sampler_nsga2" + SUFFIX),
    "random":  dict(cfg=lambda: sampler_cfg("random"), target=TRIALS_SAMPLER, study="clma_sampler_random" + SUFFIX),
}

COUNTED = (optuna.trial.TrialState.RUNNING, optuna.trial.TrialState.COMPLETE,
           optuna.trial.TrialState.PRUNED, optuna.trial.TrialState.FAIL)


def n_started(study) -> int:
    return sum(1 for t in study.get_trials(deepcopy=False) if t.state in COUNTED)


def clean_rrg():
    if KEEP_RRG:
        return
    # RRG cache only pays off WITHIN one flow invocation (3 seeds reuse it); across trials the
    # content-hashed arch name changes, so old RRGs are dead weight (~1-3 GB per trial — this is
    # what filled the 50 GB overlay). The dirs are per-worker binds, nothing else reads them.
    for d in ("rrg_3d", "base_rrg"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            for f in os.listdir(p):
                try:
                    os.remove(os.path.join(p, f))
                except OSError:
                    pass


def open_study(name: str, cfg: SearchConfig):
    storage = journal_storage(os.path.join(WORK, "journal", f"{name}.log"))
    return optuna.create_study(directions=["minimize", "minimize"], study_name=name,
                               storage=storage, load_if_exists=True, sampler=_make_sampler(cfg))


def contribute(key: str) -> None:
    sd = STUDY_DEFS[key]
    cfg = sd["cfg"]()
    sd["study"] = sd["study"] or columns_study_name()
    study = open_study(sd["study"], cfg)
    # One reference run shared by every study with the same benchmark/grid/ratios, so the
    # sampler comparison uses a common denominator (see baseline_signature).
    bpath = os.path.join(WORK, "journal", "baseline_" + baseline_signature(cfg) + ".json")
    objective = make_objective(cfg, study=study, shared_baseline_path=bpath)
    while n_started(study) < sd["target"]:
        try:
            study.optimize(objective, n_trials=1)
        except Exception as e:  # one bad trial must not kill the worker
            print(f"[w{WORKER_ID}] {key}: trial errored: {e}", flush=True)
        clean_rrg()
        done = [t for t in study.get_trials(deepcopy=False)
                if t.state == optuna.trial.TrialState.COMPLETE]
        print(f"[w{WORKER_ID}] {key}: {n_started(study)}/{sd['target']} started, "
              f"{len(done)} complete", flush=True)
    print(f"[w{WORKER_ID}] {key}: target reached, moving on", flush=True)


def promote() -> None:
    """Route the candidates that matter from the (placement-fidelity) columns study.

    Candidates, in priority order: the 3D reference and the 2D baseline (denominators for
    the paper's numbers), the Pareto set, the top PROMOTE_TOP trials by CPD objective, and
    PROMOTE_RANDOM other trials drawn at random (fixed RNG) so the placement-vs-routed
    rank correlation is measured on an unbiased sample, not only on the winners.
    Workers split candidates via lock files; each result is one JSON file."""
    cfg = columns_cfg()
    name = columns_study_name()
    study = open_study(name, cfg)
    # Wait for in-flight search trials so the candidate list is final.
    while any(t.state == optuna.trial.TrialState.RUNNING for t in study.get_trials(deepcopy=False)):
        time.sleep(60)
    done = [t for t in study.get_trials(deepcopy=False) if t.state == optuna.trial.TrialState.COMPLETE]
    by_num = {t.number: t for t in done}
    order = ["ref", "2d"]
    order += [t.number for t in sorted(study.best_trials, key=lambda t: t.values[0])]
    order += [t.number for t in sorted(done, key=lambda t: t.values[0])[:PROMOTE_TOP]]
    rest = [t.number for t in done if t.number not in order]
    random.Random(0).shuffle(rest)
    order += rest[:PROMOTE_RANDOM]
    seen, cands = set(), []
    for c in order:
        if c not in seen:
            seen.add(c)
            cands.append(c)

    out_dir = os.path.join(WORK, "promote", name)
    os.makedirs(out_dir, exist_ok=True)
    for c in cands:
        out = os.path.join(out_dir, f"{c}.json")
        try:
            os.close(os.open(out + ".lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            continue                     # another worker has it (or it is done)
        rec = {"candidate": c, "study": name, "seeds": list(SEED_LIST)}
        if c == "ref":
            spec, arch_type, conn, dr = reference_columns(cfg), cfg.arch_type, 1.0, 0.739
        elif c == "2d":
            spec, arch_type, conn, dr = None, "2d", 1.0, 0.739
        else:
            t = by_num[c]
            ft = optuna.trial.FixedTrial(t.params)
            spec = sample_columns(ft, cfg)
            arch_type, conn, dr = cfg.arch_type, t.params.get("connectivity", 1.0), t.params.get("delay_ratio", 0.739)
            rec.update(search_values=t.values, search_cpd=t.user_attrs.get("cpd_raw"),
                       search_wl=t.user_attrs.get("wl_raw"), pareto=t.number in {b.number for b in study.best_trials})
        info = {}
        metrics, err = _run_one(cfg, spec, f"{cfg.run_tag}p{c}", arch_type, conn, dr,
                                info=info, fidelity="route")
        rec.update(route_cpd=metrics[0] if metrics else None, route_wl=metrics[1] if metrics else None,
                   error=err, per_seed=info.get("per_seed"), t_total_s=info.get("t_total_s"))
        with open(out + ".tmp", "w") as f:
            json.dump(rec, f, indent=1)
        os.replace(out + ".tmp", out)
        clean_rrg()
        print(f"[w{WORKER_ID}] promote {c}: cpd={rec['route_cpd']} wl={rec['route_wl']} err={err}", flush=True)
    print(f"[w{WORKER_ID}] promote: no candidates left", flush=True)


if __name__ == "__main__":
    os.makedirs(os.path.join(WORK, "journal"), exist_ok=True)
    time.sleep(WORKER_ID * 3)  # stagger startup so 16 workers don't hammer the lock at once
    print(f"[w{WORKER_ID}] start: studies={STUDIES} seeds={SEED_LIST} cw={CW} "
          f"batch={BATCH or 'n/a'} targets: columns={TRIALS_COLUMNS} sampler={TRIALS_SAMPLER} "
          f"columns design={COLUMNS_DESIGN} fidelity={FIDELITY} tall={TALL}", flush=True)
    for key in STUDIES:
        if key == "promote":
            promote()
            continue
        if key not in STUDY_DEFS:
            print(f"[w{WORKER_ID}] unknown study '{key}' (skipping)", flush=True)
            continue
        contribute(key)
    print(f"[w{WORKER_ID}] ALL DONE", flush=True)
