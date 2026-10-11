# Collect verified campaign results into one markdown summary. Enforces the gate: only
# counts runs whose vpr_stdout.log says "VPR succeeded" with real CPD/WL. Dedups symlinked
# logs, groups a config's seed runs and reports the geomean. Reads the optuna studies from
# the JournalStorage files in <work>/journal (sqlite is gone — it died on Lustre with
# 'disk I/O error' in run 11659291). Safe to run after a partial campaign.
# argv: [out=<work>/campaign_summary.md] [work_root=/work]
import os
import re
import sys
import glob
import math

WORK = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WORK", "/work")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, "campaign_summary.md")
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
sys.path[:0] = [CODE, ROOT]  # for lazagna_optuna.journal_storage

CPD = re.compile(r"Final critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
WL = re.compile(r"Total wirelength:\s*(\d+)")
PB = re.compile(r"^\s*(io|clb|complex_dsp|spram|dsp)\s*:\s*(\d+)", re.M)


def parse_vpr(path):
    try:
        t = open(path, errors="ignore").read()
    except OSError:
        return None
    if "VPR succeeded" not in t:
        return None
    mc, mw = CPD.search(t), WL.search(t)
    if not (mc and mw):
        return None
    return {"cpd_ns": float(mc.group(1)), "wl": float(mw.group(1)),
            "blocks": {k: int(v) for k, v in PB.findall(t)}}


def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def collect_vpr():
    """Walk every worker's (and the extras job's) tasks_run under the work root."""
    groups = {}
    seen = set()
    for lp in glob.glob(os.path.join(WORK, "*", "tasks_run", "**", "vpr_stdout.log"),
                        recursive=True):
        rp = os.path.realpath(lp)
        if rp in seen:
            continue
        seen.add(rp)
        r = parse_vpr(lp)
        if not r:
            continue
        # folder: 3d_<type>_cw_<cw>_<WxH>_..._<experiment_name>_vp_<delay>_run<N>_<ts>
        # (fast flow: <folder>/seed_<N>/vpr_stdout.log)
        if os.path.basename(os.path.dirname(lp)).startswith("seed_"):
            folder = os.path.basename(os.path.dirname(os.path.dirname(lp)))
        else:
            folder = os.path.basename(lp.split("/task_")[0])
        key = folder.split("_vp_")[0]
        groups.setdefault(key, []).append(r)
    return groups


def study_summary(name):
    path = os.path.join(WORK, "journal", f"{name}.log")
    if not os.path.exists(path):
        return None
    import optuna
    from lazagna_optuna import journal_storage
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        study = optuna.load_study(study_name=name, storage=journal_storage(path))
    except Exception as e:
        return {"error": str(e)[:200]}
    trials = study.get_trials(deepcopy=False)
    done = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
    out = {"total": len(trials), "complete": len(done),
           "baseline_cpd": study.user_attrs.get("baseline_cpd"),
           "baseline_wl": study.user_attrs.get("baseline_wl"), "best": None}
    if done:
        # objectives are (-cpd_impr%, -wl_impr%): smaller = better
        b = min(done, key=lambda t: t.values[0])
        out["best"] = {"trial": b.number,
                       "cpd_impr_pct": b.user_attrs.get("cpd_impr_pct"),
                       "wl_impr_pct": b.user_attrs.get("wl_impr_pct"),
                       "cpd_raw": b.user_attrs.get("cpd_raw"),
                       "wl_raw": b.user_attrs.get("wl_raw")}
    return out


def spearman(xs, ys):
    """Rank correlation without scipy (average ranks for ties)."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx and sy else float("nan")


def promote_section():
    """Routed results of promoted candidates, % vs routed 3D reference and vs 2D, and how
    well the placement-fidelity search objective ranks layouts (Spearman)."""
    import json
    lines = []
    for sdir in sorted(glob.glob(os.path.join(WORK, "promote", "*"))):
        recs = {}
        for f in glob.glob(os.path.join(sdir, "*.json")):
            r = json.load(open(f))
            recs[str(r["candidate"])] = r
        if not recs:
            continue
        ref, two = recs.get("ref", {}), recs.get("2d", {})
        rc, rw = ref.get("route_cpd"), ref.get("route_wl")
        tc, tw = two.get("route_cpd"), two.get("route_wl")
        lines += ["", f"### {os.path.basename(sdir)}", ""]
        if rc and tc:
            lines.append(f"- **3D reference vs 2D** (routed, seeds {ref.get('seeds')}): "
                         f"CPD {100*(tc-rc)/tc:+.2f}%, WL {100*(tw-rw)/tw:+.2f}% "
                         f"(3D {rc*1e9:.3f} ns / {rw:.0f}; 2D {tc*1e9:.3f} ns / {tw:.0f})")
        else:
            lines.append(f"- reference: {ref.get('error') or 'pending'}; 2D: {two.get('error') or 'pending'}")
        lines += ["", "| trial | pareto | search CPD (ns, place est.) | routed CPD (ns) | routed WL | "
                  "CPD vs ref | WL vs ref | CPD vs 2D | error |", "|---|---|---|---|---|---|---|---|---|"]
        trials = [r for k, r in recs.items() if k not in ("ref", "2d")]
        for r in sorted(trials, key=lambda r: (r.get("route_cpd") is None, r.get("route_cpd") or 0)):
            c, w = r.get("route_cpd"), r.get("route_wl")
            f = lambda v, base: f"{100*(base-v)/base:+.2f}%" if (v and base) else "-"
            lines.append(f"| {r['candidate']} | {'y' if r.get('pareto') else ''} | "
                         f"{(r.get('search_cpd') or 0)*1e9:.3f} | {(c or 0)*1e9:.3f} | {w or 0:.0f} | "
                         f"{f(c, rc)} | {f(w, rw)} | {f(c, tc)} | {(r.get('error') or '')[:60]} |")
        pairs = [(r["search_cpd"], r["route_cpd"], r["search_wl"], r["route_wl"]) for r in trials
                 if r.get("search_cpd") and r.get("route_cpd") and r.get("search_wl") and r.get("route_wl")]
        if pairs:
            rho_c = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            rho_w = spearman([p[2] for p in pairs], [p[3] for p in pairs])
            lines += ["", f"- Placement estimate vs routed, Spearman over {len(pairs)} trials: "
                      f"CPD rho={rho_c:.2f}, WL rho={rho_w:.2f} (includes the random sample; "
                      f"rho >~0.7 supports placement-fidelity search)"]
    return lines


def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    groups = collect_vpr()
    lines = ["# Campaign Results Summary", "",
             "Only `VPR succeeded` runs with real CPD/WL (verification gate). Per config: geomean",
             "over its seed runs.", "",
             "## Per-config VPR results (verified, seed-geomean)", "",
             "| config (folder before _vp_) | seeds | CPD geomean (ns) | WL geomean | clb | complex_dsp | spram | io |",
             "|---|---|---|---|---|---|---|---|"]
    for key in sorted(groups):
        rs = groups[key]
        b = rs[0]["blocks"]
        lines.append(f"| {key} | {len(rs)} | {geomean([r['cpd_ns'] for r in rs]):.4f} | "
                     f"{geomean([r['wl'] for r in rs]):.0f} | {b.get('clb','-')} | "
                     f"{b.get('complex_dsp','-')} | {b.get('spram','-')} | {b.get('io','-')} |")
    if not groups:
        lines.append("| (none succeeded yet) | | | | | | | |")

    lines += ["", f"Total verified configs: {len(groups)}", "", "## Optuna studies (journal)", ""]
    # Discover studies from the journal dir so batch-ablation suffixes (…_b25) are picked up.
    found = sorted(os.path.basename(p)[:-4]
                   for p in glob.glob(os.path.join(WORK, "journal", "*.log")))
    for name in found or ["eltwise_columns", "clma_sampler_tpe",
                          "clma_sampler_nsga2", "clma_sampler_random"]:
        s = study_summary(name)
        if s is None:
            lines.append(f"- **{name}**: (no journal)")
        elif "error" in s:
            lines.append(f"- **{name}**: load error: {s['error']} - FLAG")
        elif s["best"]:
            bb = s["best"]
            cpd_i = bb["cpd_impr_pct"]; wl_i = bb["wl_impr_pct"]
            cpd_s = f"{cpd_i:+.2f}%" if cpd_i is not None else "?"
            wl_s = f"{wl_i:+.2f}%" if wl_i is not None else "?"
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; best trial "
                         f"{bb['trial']}: CPD {cpd_s}, WL {wl_s} vs reference "
                         f"(baseline CPD={s['baseline_cpd']}, WL={s['baseline_wl']})")
        else:
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; "
                         f"NO completed trials - FLAG")

    pl = promote_section()
    if pl:
        lines += ["", "## Promoted candidates (routed)"] + pl
    lines += ["", "## Notes",
              "- Study 'best trial' % is at the study's search fidelity (placement estimates for",
              "  *_place studies) vs the 3D reference at that fidelity; the routed numbers are in",
              "  'Promoted candidates'. 3D-vs-2D for extra designs: extras_<jobid>.out, grep IMPROVEMENT.",
              "- Any improvement outside ~0-16% => suspect contamination/degenerate; verify."]
    open(OUT, "w").write("\n".join(lines) + "\n")
    print(f"wrote {OUT}: {len(groups)} verified configs", flush=True)


if __name__ == "__main__":
    main()
