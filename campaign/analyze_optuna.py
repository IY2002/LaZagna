# Summarize the structured Optuna studies (run INSIDE the container: optuna is not on the host).
#   sbatch -A gts-<PI> --export=ALL,WORK_ROOT=<study_optuna dir>,SCRIPT=/campaign/analyze_optuna.py run_script.sbatch
# Writes /work/optuna_summary.json and /work/optuna_summary.md, plus /work/tasks_validate.jsonl:
# 5-seed "custom" validation tasks for the top-K layouts of each study (structured params),
# to be run with experiment.sbatch in the main study dir.
import glob
import json
import math
import os
import sys

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
TOPK = int(os.environ.get("TOPK", "3"))
sys.path[:0] = [CODE, ROOT]
import optuna
from lazagna_optuna import journal_storage

optuna.logging.set_verbosity(optuna.logging.WARNING)
PARAMS = ["dsp_on_l0", "bram_on_l0", "cluster", "stagger", "band_pos"]


def spearman(xs, ys):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2.0
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys); mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    c = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx)); sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return c / (sx * sy) if sx and sy else float("nan")


summary, md, tasks = {}, ["# Structured layout search (Optuna, routed, 3 seeds)", ""], []
for log in sorted(glob.glob(os.path.join(WORK, "journal", "*.log"))):
    name = os.path.basename(log)[:-4]
    try:
        st = optuna.load_study(study_name=name, storage=journal_storage(log))
    except Exception as e:
        print("skip", name, e); continue
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not done or "dsp_on_l0" not in done[0].params:
        continue
    design = name.replace("columns_", "").split("_tall")[0]
    rows = [{"n": t.number, **{p: t.params[p] for p in PARAMS},
             "cpd_impr": t.user_attrs.get("cpd_impr_pct"), "wl_impr": t.user_attrs.get("wl_impr_pct")}
            for t in done]
    # Normalized fractions on layer 0 (0.5 = balanced like the reference)
    n_dsp_tot = max(r["dsp_on_l0"] for r in rows) or 1
    corr = {}
    for p in PARAMS:
        xs = [r[p] for r in rows]
        corr[p] = {"cpd": spearman(xs, [r["cpd_impr"] for r in rows]),
                   "wl": spearman(xs, [r["wl_impr"] for r in rows])}
    # imbalance = how far from an even per-layer split
    for r in rows:
        r["imbalance"] = abs(r["dsp_on_l0"] / max(1, n_dsp_tot) - 0.5) * 2
    corr["imbalance(dsp)"] = {"cpd": spearman([r["imbalance"] for r in rows], [r["cpd_impr"] for r in rows]),
                              "wl": spearman([r["imbalance"] for r in rows], [r["wl_impr"] for r in rows])}
    score = lambda r: (r["cpd_impr"] or -99) + (r["wl_impr"] or -99)
    top = sorted(rows, key=score, reverse=True)[:TOPK]
    pareto = [t.number for t in st.best_trials]
    summary[name] = {"design": design, "n_complete": len(done), "baseline_cpd": st.user_attrs.get("baseline_cpd"),
                     "corr": corr, "top": top, "pareto": pareto, "rows": rows}
    md += [f"## {design} ({len(done)} trials)", "",
           "| parameter | Spearman vs CPD gain | Spearman vs WL gain |", "|---|---|---|"]
    md += [f"| {p} | {c['cpd']:+.2f} | {c['wl']:+.2f} |" for p, c in corr.items()]
    md += ["", "Top trials (sum of CPD + WL gain vs aligned reference, 3 seeds):", "",
           "| trial | dsp_on_l0 | bram_on_l0 | cluster | stagger | band_pos | CPD % | WL % |",
           "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['n']} | {r['dsp_on_l0']} | {r['bram_on_l0']} | {r['cluster']:.2f} | {r['stagger']:.2f} | "
           f"{r['band_pos']:.2f} | {r['cpd_impr']:+.2f} | {r['wl_impr']:+.2f} |" for r in top]
    md.append("")
    full = {"koios": ["tpu_like.small.os", "attention_layer", "tpu_like.small.ws", "conv_layer", "eltwise_layer",
                      "robot_rl", "reduction_layer", "spmv", "clstm_like.small"],
            "vtr": ["stereovision1", "stereovision2", "arm_core", "mkDelayWorker32B", "LU8PEEng"]}
    entry = next(f"{s}/{d}" for s, ds in full.items() for d in ds if d.replace(".", "_") == design)
    for r in top:
        tasks.append({"id": f"custom__{design}__t{r['n']}", "kind": "custom", "design": entry, "seeds": 5,
                      "structured": {p: r[p] for p in PARAMS}})

json.dump(summary, open(os.path.join(WORK, "optuna_summary.json"), "w"), indent=1)
open(os.path.join(WORK, "optuna_summary.md"), "w").write("\n".join(md))
open(os.path.join(WORK, "tasks_validate.jsonl"), "w").write("\n".join(json.dumps(t) for t in tasks) + "\n")
print("\n".join(md))
