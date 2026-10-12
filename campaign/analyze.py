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
    """Untagged results only; tagged runs (e.g. 10-seed confirmations) are in load_tagged()."""
    rows = {}
    for f in glob.glob(os.path.join(WORK, "results", "*.json")):
        r = json.load(open(f))
        if not r["task"].get("tag") and r["task"].get("loc", "repeated_interval") == "repeated_interval":
            rows[r["task"]["id"]] = r
    return rows


def load_tagged():
    rows = {}
    for f in glob.glob(os.path.join(WORK, "results", "*.json")):
        r = json.load(open(f))
        if r["task"].get("tag") or r["task"].get("loc", "repeated_interval") != "repeated_interval":
            rows[r["task"]["id"]] = r
    return rows


def confirm(tagged, untagged, lines):
    """10-seed confirmations (tag s10): each layout vs aligned at 10 seeds, and location patterns."""
    by = {}
    for r in tagged.values():
        if r["task"].get("tag") == "s10" and r["task"]["kind"] == "layout" and "error" not in r:
            by.setdefault(short(r["task"]["design"]), {})[r["task"]["layout"]] = r
    designs = sorted(d for d in by if "aligned" in by[d])
    if designs:
        lays = sorted({L for d in designs for L in by[d] if L != "aligned"})
        lines += ["## RQ2 confirmation (10 paired seeds)", "",
                  "| design | layout | CPD gain % vs aligned | WL gain % vs aligned | seeds |", "|---|---|---|---|---|"]
        for d in designs:
            for L in lays:
                if L in by[d]:
                    (c, cci, n), (w, wci, _) = paired(by[d]["aligned"].get("3d"), by[d][L].get("3d"))
                    lines.append(f"| {d} | {L} | {fmt(c, cci)} | {fmt(w, wci)} | {n} |")
        lines.append("")
    loc = {}
    for r in tagged.values():
        if r["task"]["kind"] == "conn" and r["task"].get("loc", "repeated_interval") != "repeated_interval" and "error" not in r:
            loc.setdefault(short(r["task"]["design"]), {})[(r["task"]["loc"], float(r["task"]["conn"]))] = r
    if loc:
        full = {short(r["task"]["design"]): r for r in untagged.values() if r["task"]["kind"] == "rq1" and "error" not in r}
        ri = {}
        for r in untagged.values():
            if r["task"]["kind"] == "conn" and float(r["task"].get("vconn", 1)) == 1.0 and "error" not in r:
                ri[(short(r["task"]["design"]), float(r["task"]["conn"]))] = r
        lines += ["## RQ3: where to put the 3D switch blocks (fixed budget)", "",
                  "Change vs full connectivity. repeated_interval = evenly interleaved (the default).", "",
                  "| design | p | pattern | CPD vs full % | WL vs full % |", "|---|---|---|---|---|"]
        for d in sorted(loc):
            if d not in full:
                continue
            ps = sorted({p for (_, p) in loc[d]})
            for p_ in ps:
                if (d, p_) in ri:
                    (c, cci, _), (w, wci, _) = paired(full[d]["3d"], ri[(d, p_)]["3d"])
                    lines.append(f"| {d} | {p_:g} | repeated_interval | {fmt(c, cci)} | {fmt(w, wci)} |")
                for (L, pp), r in sorted(loc[d].items()):
                    if pp == p_:
                        (c, cci, _), (w, wci, _) = paired(full[d]["3d"], r["3d"])
                        lines.append(f"| {d} | {p_:g} | {L} | {fmt(c, cci)} | {fmt(w, wci)} |")
        lines.append("")


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


def hb_share(r):
    """Fraction of the used area (tile rows) taken by hard blocks: DSP 4 rows, BRAM 6 rows."""
    dm = r["sizing"]["demand"]
    clb, dsp, bram = dm.get("clb", 0), dm.get("complex_dsp", 0), dm.get("spram", 0)
    tot = clb + 4 * dsp + 6 * bram
    return (4 * dsp + 6 * bram) / tot if tot else 0.0


def spearman(xs, ys):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
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
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    c = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx)); sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return c / (sx * sy) if sx and sy else float("nan")


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
    # What explains the gain? Spearman of the gain against device and design properties.
    feats = {
        "2D device side (sqrt tiles)": lambda d, r: math.sqrt(r["sizing"]["tiles_2d"]),
        "hard-block share of used tiles": lambda d, r: hb_share(r),
        "CLB utilization": lambda d, r: d["u"]["clb"],
        "max(DSP,BRAM) utilization": lambda d, r: max(d["u"]["complex_dsp"], d["u"]["spram"]),
    }
    byd = {short(r["task"]["design"]): r for r in rows.values() if r["task"]["kind"] == "rq1" and "error" not in r}
    lines += ["| property | Spearman vs CPD gain | Spearman vs WL gain |", "|---|---|---|"]
    for name, fn in feats.items():
        xs = [fn(d, byd[d["design"]]) for d in data]
        lines.append(f"| {name} | {spearman(xs, [d['c'] for d in data]):+.2f} | "
                     f"{spearman(xs, [d['w'] for d in data]):+.2f} |")
    lines.append("")

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
    # The RQ1 3D run uses the same device and the same (aligned) reference layout.
    for tid, r in rows.items():
        d = short(r["task"]["design"])
        if r["task"]["kind"] == "rq1" and "error" not in r and d in by and "aligned" not in by[d]:
            by[d]["aligned"] = {"3d": r["3d"]}
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
    agg = {"p": {}, "v": {}}   # strategy -> links -> [(cpd, wl) per design]
    for i, d in enumerate(designs):
        full = by[d][(1.0, 1.0)]["3d"]
        for (p, v), r in sorted(by[d].items()):
            if (p, v) == (1.0, 1.0):
                continue
            (c, cci, _), (w, wci, _) = paired(full, r["3d"])
            lines.append(f"| {d} | p={p:g}, v={v:g} | {p*v:.2f} | {fmt(c, cci)} | {fmt(w, wci)} |")
            if v == 1.0:
                agg["p"].setdefault(p, []).append((c, w))
            elif p == 1.0:
                agg["v"].setdefault(v, []).append((c, w))
        two = paired(full, by[d][(1.0, 1.0)]["2d"])
        lines.append(f"| {d} | 2D device | 0 | {fmt(*two[0][:2])} | {fmt(*two[1][:2])} |")
    lines += ["", "**Mean over designs, by strategy** (same link budget p·v):", "",
              "| links | fewer 3D switch blocks: CPD / WL % | fewer crossing channels: CPD / WL % |", "|---|---|---|"]
    levels = sorted(set(agg["p"]) | set(agg["v"]))
    for x in levels:
        cell = []
        for k in ("p", "v"):
            vals = agg[k].get(x)
            if vals:
                mc = sum(q[0] for q in vals) / len(vals); mw = sum(q[1] for q in vals) / len(vals)
                cell.append(f"{mc:+.1f} / {mw:+.1f} (n={len(vals)})")
            else:
                cell.append("–")
        lines.append(f"| {x:g} | {cell[0]} | {cell[1]} |")
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.4))
    styles = {"p": (BLUE, "-", "o", "fewer 3D switch blocks (p, all channels cross)"),
              "v": (ORANGE, "--", "s", "fewer crossing channels per switch block (v, every SB 3D)")}
    for k, (col, ls, mk, lab) in styles.items():
        xs = sorted(agg[k]) + [1.0]
        for ax, j in ((axes[0], 0), (axes[1], 1)):
            means = [sum(q[j] for q in agg[k][x]) / len(agg[k][x]) for x in xs[:-1]] + [0.0]
            lo = [min(q[j] for q in agg[k][x]) for x in xs[:-1]] + [0.0]
            hi = [max(q[j] for q in agg[k][x]) for x in xs[:-1]] + [0.0]
            ax.fill_between(xs, lo, hi, color=col, alpha=0.12, lw=0)
            ax.plot(xs, means, color=col, ls=ls, lw=2, marker=mk, ms=6, label=lab)
    for ax, t in ((axes[0], "CPD vs full connectivity (%)"), (axes[1], "WL vs full connectivity (%)")):
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_xscale("log")
        ax.set_xlabel("relative number of vertical links (p·v), log scale")
        ax.set_title(t, loc="left")
    axes[1].legend(loc="lower right", fontsize=7.5)
    fig.text(0.01, 0.01, f"mean over {len(designs)} designs; band = min–max across designs", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(os.path.join(FIGS, "rq3_connectivity.png"), dpi=200)
    plt.close(fig)
    lines += ["", "![RQ3](figs/rq3_connectivity.png)", ""]


def recommended(rows, tagged, lines, plt):
    """Synthesis of RQ2+RQ3: gain over 2D of (a) full 3D aligned, (b) type-dedicated layers,
    (c) recommended = type-dedicated layers + only 10% of channels crossing at every SB.
    Also inter-layer delay sensitivity (tag delay)."""
    rq1 = {short(r["task"]["design"]): r for r in rows.values() if r["task"]["kind"] == "rq1" and "error" not in r}
    split = {short(r["task"]["design"]): r for r in rows.values()
             if r["task"]["kind"] == "layout" and r["task"]["layout"] == "split_types" and "error" not in r}
    rec = {short(r["task"]["design"]): r for r in tagged.values() if r["task"].get("tag") == "rec" and "error" not in r}
    designs = sorted(d for d in rq1 if d in rec)
    if designs:
        lines += ["## Recommended 3D architecture vs 2D", "",
                  "Gain over the equal-resource 2D device (positive = better). *aligned*: full 3D connectivity, "
                  "evenly spread hard blocks identical on both layers. *split*: DSP on layer 0, BRAM on layer 1. "
                  "*recommended*: split + only 10% of channels crossing at every switch block (10× fewer vertical links).", "",
                  "| design | aligned CPD / WL % | split CPD / WL % | recommended CPD / WL % |", "|---|---|---|---|"]
        ratios = {"aligned": ([], []), "split": ([], []), "recommended": ([], [])}
        for d in designs:
            two = rq1[d]["2d"]
            cells = []
            for name, side in (("aligned", rq1[d]["3d"]), ("split", (split.get(d) or {}).get("3d")),
                               ("recommended", rec[d]["3d"])):
                if not side:
                    cells.append("–"); continue
                (c, cci, _), (w, wci, _) = paired(two, side)
                cells.append(f"{fmt(c, cci)} / {fmt(w, wci)}")
                g2, g3 = common_gm(two, side)
                if g2:
                    ratios[name][0].append(g3[0] / g2[0]); ratios[name][1].append(g3[1] / g2[1])
            lines.append(f"| {d} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("**Geomean gain over 2D:** " + "; ".join(
            f"{k}: CPD {gm_ratio_pct(v[0]):+.1f}%, WL {gm_ratio_pct(v[1]):+.1f}% (n={len(v[0])})"
            for k, v in ratios.items() if v[0]))
        lines.append("")
        fig, ax = plt.subplots(figsize=(5.2, 2.8))
        names = [k for k in ratios if ratios[k][0]]
        xs = range(len(names))
        cp = [gm_ratio_pct(ratios[k][0]) for k in names]; wl = [gm_ratio_pct(ratios[k][1]) for k in names]
        ax.bar([x - 0.18 for x in xs], cp, width=0.34, color=BLUE, label="CPD")
        ax.bar([x + 0.18 for x in xs], wl, width=0.34, color=ORANGE, label="Wirelength")
        for x, a, b in zip(xs, cp, wl):
            ax.text(x - 0.18, a, f"{a:+.1f}", ha="center", va="bottom", fontsize=8, color=INK)
            ax.text(x + 0.18, b, f"{b:+.1f}", ha="center", va="bottom", fontsize=8, color=INK)
        ax.set_xticks(list(xs), ["full 3D\n(aligned)", "type-dedicated\nlayers", "recommended\n(+10% links)"])
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(f"Geomean gain over 2D (%), {len(designs)} designs", loc="left")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "recommended_vs_2d.png"), dpi=200); plt.close(fig)
        lines += ["![recommended](figs/recommended_vs_2d.png)", ""]
    # delay sensitivity
    dl = {}
    for r in tagged.values():
        if r["task"].get("tag") == "delay" and "error" not in r:
            kind = "recommended" if r["task"].get("vconn", 1) != 1 else "aligned"
            dl.setdefault(short(r["task"]["design"]), {})[(kind, float(r["task"]["delay"]))] = r
    for d in list(dl):
        if d in rq1:
            dl[d][("aligned", 0.739)] = {"3d": rq1[d]["3d"]}
            if d in rec:
                dl[d][("recommended", 0.739)] = {"3d": rec[d]["3d"]}
    dd = sorted(d for d in dl if d in rq1)
    if dd:
        lines += ["## Sensitivity to inter-layer delay", "",
                  "Gain over 2D vs the inter-layer delay ratio (vertical-link delay relative to an L4 wire driver; "
                  "0.739 = default).", "",
                  "| design | config | " + " | ".join(f"d={x:g}" for x in (0.3, 0.739, 1.5, 3.0)) + " |",
                  "|---|---|" + "---|" * 4]
        agg = {}
        for d in dd:
            for kind in ("aligned", "recommended"):
                cells = []
                for x in (0.3, 0.739, 1.5, 3.0):
                    r = dl[d].get((kind, x))
                    if not r:
                        cells.append("–"); continue
                    (c, cci, _), (w, wci, _) = paired(rq1[d]["2d"], r["3d"])
                    cells.append(f"{c:+.1f} / {w:+.1f}")
                    agg.setdefault((kind, x), []).append((c, w))
                lines.append(f"| {d} | {kind} | " + " | ".join(cells) + " |")
        lines += ["", "(cells: CPD / WL gain % over 2D)", ""]
        fig, axes = plt.subplots(1, 2, figsize=(9, 3))
        for kind, col, ls in (("aligned", BLUE, "-"), ("recommended", ORANGE, "--")):
            xs = [x for x in (0.3, 0.739, 1.5, 3.0) if (kind, x) in agg]
            for ax, j in ((axes[0], 0), (axes[1], 1)):
                ax.plot(xs, [sum(q[j] for q in agg[(kind, x)]) / len(agg[(kind, x)]) for x in xs],
                        color=col, ls=ls, marker="o", lw=2, label=kind)
        for ax, t in ((axes[0], "CPD gain over 2D (%)"), (axes[1], "WL gain over 2D (%)")):
            ax.axhline(0, color=INK2, lw=0.8); ax.set_xlabel("inter-layer delay ratio"); ax.set_title(t, loc="left")
        axes[1].legend(fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "delay_sensitivity.png"), dpi=200); plt.close(fig)
        lines += [f"![delay](figs/delay_sensitivity.png)", f"(mean over {len(dd)} designs)", ""]


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
    confirm(load_tagged(), rows, lines)
    recommended(rows, load_tagged(), lines, plt)
    # Optuna top layouts re-run at 5 seeds vs the aligned reference (RQ1 3D side, same seeds)
    cust = [r for r in rows.values() if r["task"]["kind"] == "custom" and "error" not in r]
    if cust:
        ref = {short(r["task"]["design"]): r for r in rows.values() if r["task"]["kind"] == "rq1" and "error" not in r}
        lines += ["## RQ2: best searched layouts, re-run at 5 seeds", "",
                  "| design | trial | DSP on L0 / BRAM on L0 | cluster | stagger | CPD gain % vs aligned | WL gain % vs aligned |",
                  "|---|---|---|---|---|---|---|"]
        for r in sorted(cust, key=lambda r: r["task"]["id"]):
            d = short(r["task"]["design"]); p = r["task"].get("structured", {})
            if d in ref:
                (c, cci, _), (w, wci, _) = paired(ref[d]["3d"], r["3d"])
                tot_d, tot_b = 2 * r["cols_per_layer"][1], 2 * r["cols_per_layer"][2]
                lines.append(f"| {d} | {r['task']['id'].split('__')[-1]} | {p.get('dsp_on_l0')}/{tot_d} , "
                             f"{p.get('bram_on_l0')}/{tot_b} | {p.get('cluster', 0):.2f} | {p.get('stagger', 0):.2f} | "
                             f"{fmt(c, cci)} | {fmt(w, wci)} |")
        lines.append("")
    if failed:
        lines += ["## Failed runs", ""] + [f"- {t}: {(rows[t].get('error') or (rows[t].get('3d') or {}).get('error') or (rows[t].get('2d') or {}).get('error'))[:160]}" for t in sorted(failed)] + [""]
    open(os.path.join(OUT, "tables.md"), "w").write("\n".join(lines))
    print(f"wrote {OUT}/tables.md ({len(rows)} results, {len(failed)} with errors)")
