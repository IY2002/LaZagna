# Analysis of the fixed-configuration experiments (campaign/experiment.py results).
# Runs on the host (needs matplotlib; `module load anaconda3`):
#     python3 campaign/analyze.py campaign_work/study docs/study
# Writes <out>/tables.md and <out>/figs/*.png.
#
# Statistics. Every comparison is paired by seed (same placement seed on both sides), so
# for each design the improvement is computed per seed, then summarized as the mean and
# a 95% t-interval over seeds. Across designs: geometric mean of the per-design ratios.
# CPD for multi-clock designs is VPR's geomean intra-domain period (see lazagna_fastflow).
import glob
import json
import math
import os
import sys

WORK = sys.argv[1] if len(sys.argv) > 1 else "campaign_work/study"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/study"
FIGS = os.path.join(OUT, "figs")

# Reference palette (dataviz skill, light mode)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
DIVERGING = ["#a32f2f", "#e34948", "#f4a3a2", "#f0efec", "#9ec5f4", "#3987e5", "#184f95"]  # worse .. better
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26}


def load():
    rows = {}
    for f in glob.glob(os.path.join(WORK, "results", "*.json")):
        r = json.load(open(f))
        rows[r["task"]["id"]] = r
    return rows


def per_seed(side):
    """{seed: (cpd, wl)} for successfully routed seeds."""
    out = {}
    for p in (side or {}).get("per_seed") or []:
        if p.get("route_cpd") and p.get("route_wl"):
            out[p["seed"]] = (p["route_cpd"], p["route_wl"])
    return out


def paired(base, new):
    """Per-seed % improvement of `new` over `base` for CPD and WL -> (mean, ci95, n) each."""
    b, n = per_seed(base), per_seed(new)
    seeds = sorted(set(b) & set(n))
    res = []
    for k in (0, 1):
        xs = [100.0 * (b[s][k] - n[s][k]) / b[s][k] for s in seeds]
        if not xs:
            res.append((None, None, 0))
            continue
        m = sum(xs) / len(xs)
        if len(xs) > 1:
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            ci = T95.get(len(xs) - 1, 1.96) * sd / math.sqrt(len(xs))
        else:
            ci = float("nan")
        res.append((m, ci, len(xs)))
    return res


def common_gm(base, new):
    """Geomean (cpd, wl) of base and of new over the seeds both sides routed."""
    b, n = per_seed(base), per_seed(new)
    seeds = sorted(set(b) & set(n))
    if not seeds:
        return None, None
    g = lambda xs: math.exp(sum(math.log(x) for x in xs) / len(xs))
    return ((g([b[s][0] for s in seeds]), g([b[s][1] for s in seeds])),
            (g([n[s][0] for s in seeds]), g([n[s][1] for s in seeds])))


def gm_ratio_pct(pairs):
    """Geomean over designs of value ratio new/base, as % improvement."""
    rs = [p for p in pairs if p and p > 0]
    if not rs:
        return None
    return 100.0 * (1 - math.exp(sum(math.log(r) for r in rs) / len(rs)))


def fmt(m, ci):
    if m is None:
        return "–"
    return f"{m:+.1f} ± {ci:.1f}" if ci == ci else f"{m:+.1f}"


def short(design):
    return design.split("/", 1)[1]


def setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
        "axes.titlesize": 10, "axes.titleweight": "bold", "legend.frameon": False,
    })
    return plt


# ------------------------------------------------------------------------------- RQ1
def rq1(rows, lines, plt):
    data = []
    for tid, r in sorted(rows.items()):
        if r["task"]["kind"] != "rq1" or "error" in r:
            continue
        (c, cci, cn), (w, wci, wn) = paired(r.get("2d"), r.get("3d"))
        if cn == 0:
            continue
        sz = r["sizing"]
        g2, g3 = common_gm(r.get("2d"), r.get("3d"))
        d2 = {"cpd": g2[0], "wl": g2[1]}
        d3 = {"cpd": g3[0], "wl": g3[1]}
        u = {t: r["sizing"]["demand"].get(t, 0) / max(1, r["sizing"]["cap_2d"][t]) for t in ("clb", "complex_dsp", "spram")}
        data.append(dict(design=short(r["task"]["design"]), c=c, cci=cci, w=w, wci=wci, n=cn,
                         cr=d3["cpd"] / d2["cpd"] if d2.get("cpd") and d3.get("cpd") else None,
                         wr=d3["wl"] / d2["wl"] if d2.get("wl") and d3.get("wl") else None,
                         cpd2=d2.get("cpd"), cpd3=d3.get("cpd"), wl2=d2.get("wl"), wl3=d3.get("wl"),
                         dev2=f"{sz['width_2d']}×{sz['height_2d']}", dev3=f"2×{sz['width']}×{sz['height']}",
                         u=u))
    if not data:
        return
    data.sort(key=lambda d: -(d["c"] or 0))
    lines += ["## RQ1: 3D vs 2D at equal resources", "",
              "Improvement of the 3D device over the 2D device with the same tile and block counts "
              "(positive = 3D better). Mean ± 95% CI over paired seeds.", "",
              "| design | 2D | 3D | use CLB/DSP/BRAM (2D) | CPD 2D (ns) | CPD 3D (ns) | CPD gain % | WL gain % | seeds |",
              "|---|---|---|---|---|---|---|---|---|"]
    for d in data:
        u = d["u"]
        lines.append(f"| {d['design']} | {d['dev2']} | {d['dev3']} | "
                     f"{100*u['clb']:.0f}/{100*u['complex_dsp']:.0f}/{100*u['spram']:.0f}% | "
                     f"{d['cpd2']*1e9:.2f} | {d['cpd3']*1e9:.2f} | {fmt(d['c'], d['cci'])} | "
                     f"{fmt(d['w'], d['wci'])} | {d['n']} |")
    gc, gw = gm_ratio_pct([d["cr"] for d in data]), gm_ratio_pct([d["wr"] for d in data])
    wins_c = sum(1 for d in data if d["c"] > 0)
    wins_w = sum(1 for d in data if d["w"] > 0)
    lines += ["", f"**Geomean over {len(data)} designs: CPD {gc:+.1f}%, WL {gw:+.1f}%.** "
              f"3D wins CPD on {wins_c}/{len(data)} and WL on {wins_w}/{len(data)} designs.", ""]

    fig, axes = plt.subplots(1, 2, figsize=(9, 0.32 * len(data) + 1.2), sharey=True)
    ys = list(range(len(data)))[::-1]
    for ax, key, ci, title in ((axes[0], "c", "cci", "Critical path delay"), (axes[1], "w", "wci", "Wirelength")):
        vals = [d[key] for d in data]
        errs = [d[ci] if d[ci] == d[ci] else 0 for d in data]
        ax.barh(ys, vals, height=0.6, color=BLUE, xerr=errs, error_kw=dict(ecolor=INK2, lw=0.8, capsize=2))
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{title}: 3D gain over 2D (%)", loc="left")
        ax.set_yticks(ys, [d["design"] for d in data])
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "rq1_3d_vs_2d.png"), dpi=200)
    plt.close(fig)
    lines += ["![RQ1](figs/rq1_3d_vs_2d.png)", ""]


# ------------------------------------------------------------------------------- RQ2
LAYOUT_ORDER = ["aligned", "staggered", "hb_one_layer", "split_types", "center", "edges", "center_edges"]


def rq2(rows, lines, plt):
    by = {}
    for tid, r in rows.items():
        if r["task"]["kind"] == "layout" and "error" not in r:
            by.setdefault(short(r["task"]["design"]), {})[r["task"]["layout"]] = r
    designs = sorted(d for d in by if "aligned" in by[d])
    if not designs:
        return
    lines += ["## RQ2: hard-block placement across layers", "",
              "Each layout vs the aligned reference (evenly spread hard-block columns, identical "
              "layers) on the same 3D device, same block totals. Positive = better than aligned. "
              "Mean ± 95% CI over paired seeds.", ""]
    for metric, k in (("CPD", 0), ("WL", 1)):
        lines += [f"**{metric} gain % vs aligned**", "",
                  "| layout | " + " | ".join(designs) + " | mean |", "|---" * (len(designs) + 2) + "|"]
        mat = []
        for L in LAYOUT_ORDER[1:]:
            row, vals = [], []
            for d in designs:
                if L in by[d]:
                    p = paired(by[d]["aligned"].get("3d"), by[d][L].get("3d"))[k]
                    row.append(fmt(p[0], p[1]))
                    vals.append(p[0])
                else:
                    row.append("–")
                    vals.append(None)
            ok = [v for v in vals if v is not None]
            mean = sum(ok) / len(ok) if ok else None
            lines.append(f"| {L} | " + " | ".join(row) + f" | {mean:+.1f} |" if mean is not None else f"| {L} | " + " | ".join(row) + " | – |")
            mat.append(vals)
        lines.append("")
        # heatmap
        import numpy as np
        from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
        arr = np.array([[v if v is not None else np.nan for v in row] for row in mat], dtype=float)
        lim = max(1.0, np.nanmax(np.abs(arr))) if np.isfinite(arr).any() else 1.0
        cmap = LinearSegmentedColormap.from_list("div", DIVERGING)
        fig, ax = plt.subplots(figsize=(1.2 * len(designs) + 2.2, 3.2))
        im = ax.imshow(arr, cmap=cmap, norm=TwoSlopeNorm(0, -lim, lim), aspect="auto")
        ax.set_xticks(range(len(designs)), designs, rotation=30, ha="right")
        ax.set_yticks(range(len(LAYOUT_ORDER) - 1), LAYOUT_ORDER[1:])
        ax.grid(False)
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                if np.isfinite(arr[i, j]):
                    ax.text(j, i, f"{arr[i, j]:+.1f}", ha="center", va="center", fontsize=8,
                            color=INK if abs(arr[i, j]) < 0.6 * lim else SURFACE)
        cb = fig.colorbar(im, ax=ax, shrink=0.8)
        cb.set_label(f"{metric} gain vs aligned (%)  (blue = better)")
        ax.set_title(f"RQ2: {metric} change by hard-block layout", loc="left")
        fig.tight_layout()
        name = f"rq2_layouts_{metric.lower()}.png"
        fig.savefig(os.path.join(FIGS, name), dpi=200)
        plt.close(fig)
        lines += [f"![RQ2 {metric}](figs/{name})", ""]


# ------------------------------------------------------------------------------- RQ3
def rq3(rows, lines, plt):
    by = {}
    for tid, r in rows.items():
        if r["task"]["kind"] == "conn" and "error" not in r:
            d = short(r["task"]["design"])
            by.setdefault(d, {})[(float(r["task"]["conn"]), float(r["task"].get("vconn", 1)))] = r
    # full connectivity reference = RQ1 3D side (same reference layout, conn 1.0, vconn 1.0),
    # and the 2D device as the zero-link anchor
    for tid, r in rows.items():
        if r["task"]["kind"] == "rq1" and "error" not in r and short(r["task"]["design"]) in by:
            by[short(r["task"]["design"])][(1.0, 1.0)] = {"3d": r["3d"], "2d": r["2d"]}
    designs = sorted(d for d in by if (1.0, 1.0) in by[d])
    if not designs:
        return
    lines += ["## RQ3: vertical connectivity vs cost", "",
              "3D reference layout with a fraction p of switch blocks made 3D (all channels "
              "crossing), and with all switch blocks 3D but only a fraction v of channels "
              "crossing. Change vs full connectivity (p = 1, v = 1); positive = better. The 2D "
              "device (no vertical links) is shown for scale.", "",
              "| design | config | relative links | CPD vs full % | WL vs full % |", "|---|---|---|---|---|"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
    for i, d in enumerate(designs):
        full = by[d][(1.0, 1.0)]["3d"]
        pts = []
        for (p, v), r in sorted(by[d].items()):
            if (p, v) == (1.0, 1.0):
                continue
            (c, cci, _), (w, wci, _) = paired(full, r["3d"])
            lines.append(f"| {d} | p={p:g}, v={v:g} | {p*v:.2f} | {fmt(c, cci)} | {fmt(w, wci)} |")
            if v == 1.0:
                pts.append((p, c, w))
        two = paired(full, by[d][(1.0, 1.0)]["2d"])
        lines.append(f"| {d} | 2D device | 0 | {fmt(*two[0][:2])} | {fmt(*two[1][:2])} |")
        pts.append((1.0, 0.0, 0.0))
        pts.sort()
        col = CATEGORICAL[i % len(CATEGORICAL)]
        for ax, k in ((axes[0], 1), (axes[1], 2)):
            ax.plot([q[0] for q in pts], [q[k] for q in pts], color=col, lw=2, marker="o", ms=5, label=d)
    for ax, t in ((axes[0], "CPD vs full connectivity (%)"), (axes[1], "WL vs full connectivity (%)")):
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_xlabel("fraction of switch blocks with vertical links (p)")
        ax.set_title(t, loc="left")
    axes[1].legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "rq3_connectivity.png"), dpi=200)
    plt.close(fig)
    lines += ["", "![RQ3](figs/rq3_connectivity.png)", ""]


if __name__ == "__main__":
    os.makedirs(FIGS, exist_ok=True)
    rows = load()
    plt = setup_mpl()
    lines = [f"<!-- generated by campaign/analyze.py from {WORK}/results ({len(rows)} results) -->", ""]
    failed = [tid for tid, r in rows.items() if "error" in r or any(
        (r.get(k) or {}).get("error") for k in ("2d", "3d"))]
    rq1(rows, lines, plt)
    rq2(rows, lines, plt)
    rq3(rows, lines, plt)
    if failed:
        lines += ["## Failed runs", ""] + [f"- {t}: {(rows[t].get('error') or (rows[t].get('3d') or {}).get('error') or (rows[t].get('2d') or {}).get('error'))[:160]}" for t in sorted(failed)] + [""]
    open(os.path.join(OUT, "tables.md"), "w").write("\n".join(lines))
    print(f"wrote {OUT}/tables.md ({len(rows)} results, {len(failed)} with errors)")
