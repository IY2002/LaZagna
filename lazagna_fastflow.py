"""Fast evaluation path for architecture search: synthesize and pack ONCE, then run VPR
directly for each candidate architecture.

Why this is valid. Every candidate in a layout study uses the same block definitions (the
<models>/<complexblocklist> of the dsp_bram templates are byte-identical across the 2D, 3D SB
and 3D CB variants); only WHERE tiles sit changes. Yosys output depends on the netlist and
the block models, and VPR's packer depends on the netlist and the block definitions, and
neither uses the placement seed. So one post-synthesis BLIF and one packed .net per
benchmark serve every trial, every seed, and both the 2D and 3D devices. As a side effect
every trial is guaranteed identical block counts.

Why this is fast. The regular LaZagna flow runs Yosys + the full OpenFPGA script (fabric,
fabric Verilog, repack, bitstream) for every seed of every trial. For eltwise that was
~41 s Yosys + 426 s OpenFPGA, of which VPR itself was 44 s. Here a trial costs RRG
generation plus place (and optionally route).

Two fidelities:
  stage="place"  stop after placement; metrics are VPR's placement estimates
                 ("Placement estimated critical path delay", final BB wirelength).
                 Cheap search objective for designs whose routing takes hours.
  stage="route"  full place + route; metrics are post-route CPD / total wirelength.
                 The placement estimates are parsed as well, so every routed run also
                 contributes a (placement estimate, routed) pair for checking that the
                 cheap fidelity ranks layouts correctly.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

VPR_REL = "OpenFPGA/build/vtr-verilog-to-routing/vpr/vpr"

_PLACE_CPD = re.compile(r"Placement estimated critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
_PLACE_WL = re.compile(r"BB estimate of min-dist \(placement\) wire length:\s*(\d+)")
_ROUTE_CPD = re.compile(r"Final critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
# Multi-clock designs: VPR prints no single critical path, only the geomean period over
# clock domains (identical to the critical path delay for single-clock designs).
_PLACE_PERIOD = re.compile(r"Placement estimated geomean non-virtual intra-domain period:\s*([\d.eE+-]+)\s*ns")
_ROUTE_PERIOD = re.compile(r"Final geomean non-virtual intra-domain period:\s*([\d.eE+-]+)\s*ns")
# Require the full line: standalone VPR's stderr can splice into a stdout line mid-number.
_ROUTE_WL = re.compile(r"Total wirelength:\s*(\d+),\s*average net length")
_REPACK = "Packing failed to fit on device"


def geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("inf")


def _run(cmd, cwd, timeout_s, log_path=None):
    """Run in its own process group so a timeout kills every child. With log_path, stdout
    goes there and stderr to <log_path>.err (merging them interleaves partial lines)."""
    out = open(log_path, "w") if log_path else subprocess.PIPE
    err = open(log_path + ".err", "w") if log_path else subprocess.STDOUT
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err,
                                text=True, start_new_session=True)
        try:
            stdout, _ = proc.communicate(timeout=timeout_s)
            return proc.returncode, stdout or ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.communicate()
            return -9, f"TIMEOUT after {timeout_s}s"
    finally:
        if log_path:
            out.close()
            err.close()


def _run_once(marker: str, fn, poll_s: int = 20, max_wait_s: int = 6 * 3600):
    """Run fn() exactly once across concurrent workers sharing a filesystem.
    The first caller takes the lock and runs it; the others wait for `marker` to appear."""
    if os.path.exists(marker):
        return
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    lock = marker + ".lock"
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        waited = 0
        while not os.path.exists(marker) and waited < max_wait_s:
            time.sleep(poll_s)
            waited += poll_s
        if os.path.exists(marker):
            return
        # owner died holding the lock: take over
    try:
        fn()
        open(marker, "w").close()
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def block_signature(arch_xml: str) -> str:
    """Hash of what packing depends on: block models and block definitions, not the layout."""
    parts = [re.search(p, arch_xml, re.S) for p in (r"<models>.*?</models>",
                                                    r"<complexblocklist>.*?</complexblocklist>")]
    key = "".join(m.group(0) for m in parts if m)
    return hashlib.sha1(key.encode()).hexdigest()[:10]


# --------------------------------------------------------------------------------------
# One-time preparation: synthesis + pack
# --------------------------------------------------------------------------------------

SYNTH_FILES = ("yosys.ys", "bram.txt", "bram_map.v", "dsp_map.v", "bram_cell_sim.v",
               "merge_write_ports.py")


def synth_signature(lazagna_root: str) -> str:
    """Hash of the synthesis recipe (Yosys script + BRAM/DSP mapping files), so editing the
    flow invalidates cached BLIFs instead of silently reusing them."""
    h = hashlib.sha1()
    for name in SYNTH_FILES:
        p = os.path.join(lazagna_root, "task", "designs", name)
        h.update(name.encode())
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()[:8]


_DEMAND = re.compile(r"Netlist\s+(\d+)\s+blocks of type:\s*(\S+)")


def auto_layout_arch(template_xml: str) -> str:
    """Same arch with an auto-sized layout, so packing always fits on the first attempt
    (VPR's re-pack fallback on a too-small fixed device changes the packing)."""
    auto = """  <layout tileable="false">
    <auto_layout aspect_ratio="1.0">
      <perimeter type="io" priority="100"/>
      <corners type="EMPTY" priority="101"/>
      <fill type="clb" priority="10"/>
      <col type="complex_dsp" startx="2" starty="1" repeatx="8" priority="20"/>
      <col type="spram" startx="6" starty="1" repeatx="8" priority="20"/>
    </auto_layout>
  </layout>"""
    return re.sub(r"[ \t]*<layout\b.*?</layout>", auto, template_xml, count=1, flags=re.S)


def read_demand(pack_log: str) -> dict:
    """Packed block counts per type, e.g. {"clb": 1331, "complex_dsp": 11, "spram": 116, "io": 248}."""
    text = open(pack_log, errors="ignore").read()
    return {t: int(n) for n, t in _DEMAND.findall(text)}


_MEM = re.compile(r"Processing \S+:\n  Properties: ports=\d+ bits=(\d+) rports=(\d+) wports=(\d+) "
                  r"dbits=(\d+) abits=(\d+) words=\d+")


def synth_report(yosys_log: str) -> dict:
    """How Yosys mapped memories and multipliers, from its log.

    memories: total $mem cells seen by memory_bram; bram_cells: spram instances created;
    soft_*: memories left to memory_map (flip-flops + LUTs), split by why they did not map:
    true dual-port (2 write ports; the spram has one port), ROM (no write port; BRAM rules
    allow no init), other. small_in_bram: memories under 1/8 of a BRAM (2560 bits) that were
    still put into a BRAM."""
    t = open(yosys_log, errors="ignore").read()
    chunks = re.split(r"(?=Processing \S+:\n  Properties:)", t)
    rep = {"memories": 0, "bram_cells": len(re.findall(r"Creating ram\w+ cell", t)),
           "soft_tdp": 0, "soft_rom": 0, "soft_other": 0, "small_in_bram": 0}
    for c in chunks[1:]:
        m = _MEM.match(c)
        if not m:
            continue
        bits, _, wports = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rep["memories"] += 1
        if "No acceptable bram resources found" in c:
            key = "soft_tdp" if wports >= 2 else ("soft_rom" if wports == 0 else "soft_other")
            rep[key] += 1
        elif bits < 2560:
            rep["small_in_bram"] += 1
    stats = t.split("Printing statistics.")
    last = stats[-1] if len(stats) > 1 else ""
    for key, pat in (("mult_27x27", r"one_mult_27x27"), ("mult_18x19", r"two_mult_18x19")):
        rep[key] = sum(int(n) for n in re.findall(r"^\s+\S*" + pat + r"\S*\s+(\d+)", last, re.M))
    return rep


def prepare_benchmark(template_2d_xml: str, opts, cache_dir: str, lazagna_root: str,
                      timeout_s: int = 6 * 3600) -> dict:
    """Synthesize and pack the single benchmark in opts.benchmarks.directory, once.

    Returns {"blif", "net", "demand", "dir"}. `template_2d_xml` is the single-die template;
    its block definitions are the ones every trial uses. The cache key is benchmark name +
    block signature + synthesis-recipe signature, so every layout, grid size, seed, and the
    2D/3D devices share it, and a change to the Yosys flow re-synthesizes.
    Safe to call from many workers at once: one does the work, the rest wait.

    Steps: (1) the regular LaZagna flow, only for Yosys's BLIF (its own VPR run is ignored);
    (2) VPR --pack on that BLIF against an auto-sized device; (3) block demand from the log."""
    from lazagna_arch_model import run_lazagna, AdvancedOptions, SeedOptions
    import copy

    bench_dir = opts.benchmarks.directory.replace("{lazagna_root}", lazagna_root)
    ext = ".v" if opts.benchmarks.is_verilog else ".blif"
    srcs = sorted(glob.glob(os.path.join(bench_dir, "*" + ext)))
    if len(srcs) != 1:
        raise ValueError(f"prepare_benchmark needs exactly one {ext} in {bench_dir}, found {len(srcs)}")
    name = os.path.splitext(os.path.basename(srcs[0]))[0]
    pack_arch = auto_layout_arch(template_2d_xml)
    out = os.path.join(cache_dir, f"{name}_{block_signature(pack_arch)}_{synth_signature(lazagna_root)}")
    meta_path = os.path.join(out, "prep.json")

    def build():
        os.makedirs(out, exist_ok=True)
        arch_path = os.path.join(out, "pack_arch.xml")
        with open(arch_path, "w") as f:
            f.write(pack_arch)

        if opts.benchmarks.is_verilog:
            o = copy.deepcopy(opts)
            tag = "prep" + hashlib.sha1(out.encode()).hexdigest()[:8]
            o.experiment_name = tag
            o.architectures[0].type = "2d"
            o.seeds = SeedOptions(mode="fixed", value=1)
            o.advanced = AdvancedOptions(additional_vpr_options="--pack", vpr_only=True)
            t0 = time.time()
            res = run_lazagna(pack_arch, o, lazagna_root=lazagna_root, timeout_s=timeout_s)
            commons = glob.glob(os.path.join(lazagna_root, "tasks_run", f"*{tag}*", "task_*",
                                             "task", "run*", "vtr_arch", "*", "Common"))
            # The BLIF VPR reads is the second token of the generated vpr command.
            scripts = [p for c in commons for p in glob.glob(os.path.join(c, "*_run.openfpga"))]
            if not scripts:
                ylogs = [os.path.join(c, "yosys_output.log") for c in commons
                         if os.path.exists(os.path.join(c, "yosys_output.log"))]
                err = "; ".join(l.strip() for l in open(ylogs[0], errors="ignore")
                                if "ERROR" in l)[:400] if ylogs else ""
                raise RuntimeError(f"prepare {name}: synthesis failed: "
                                   f"{err or res['stderr'][-400:] or 'no run folder'}")
            vpr_line = next(l for l in open(scripts[0]) if l.startswith("vpr"))
            src_blif = os.path.join(os.path.dirname(scripts[0]), vpr_line.split()[2])
            ylog = os.path.join(os.path.dirname(scripts[0]), "yosys_output.log")
            if not os.path.exists(src_blif):
                err = ""
                if os.path.exists(ylog):
                    err = "; ".join(l.strip() for l in open(ylog, errors="ignore") if "ERROR" in l)[:400]
                raise RuntimeError(f"prepare {name}: synthesis failed: {err or 'no BLIF produced'}")
            shutil.copy(ylog, os.path.join(out, "yosys_output.log"))
            synth = synth_report(ylog)
            t_synth = time.time() - t0
        else:
            src_blif, t_synth, synth = srcs[0], 0.0, {}

        stem = os.path.splitext(os.path.basename(src_blif))[0]
        blif = os.path.join(out, stem + ".blif")
        shutil.copy(src_blif, blif)
        t0 = time.time()
        log = os.path.join(out, "pack_vpr_stdout.log")
        rc, msg = _run([os.path.join(lazagna_root, VPR_REL), arch_path, blif, "--pack"],
                       cwd=out, timeout_s=timeout_s, log_path=log)
        text = open(log, errors="ignore").read()
        net = os.path.join(out, stem + ".net")
        if rc != 0 or not os.path.exists(net):
            raise RuntimeError(f"prepare {name}: pack failed (rc={rc}): {msg or text[-800:]}")
        if _REPACK in text:
            raise RuntimeError(f"prepare {name}: packer fell back to re-packing on the auto device")
        meta = {"benchmark": name, "blif": blif, "net": net, "demand": read_demand(log), "synth": synth,
                "t_synth_s": round(t_synth, 1), "t_pack_s": round(time.time() - t0, 1)}
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=1)

    _run_once(os.path.join(out, ".done"), build)
    if not os.path.exists(meta_path):
        raise RuntimeError(f"prepare {name}: cache incomplete in {out}")
    meta = json.load(open(meta_path))
    meta["dir"] = out
    return meta


# --------------------------------------------------------------------------------------
# Per-trial evaluation
# --------------------------------------------------------------------------------------

def _setup_device(arch_path: str, opts, lazagna_root: str, timeout_s: int) -> dict:
    """Use LaZagna's own setup_flow to apply delay ratio / grid size to the arch and build
    the (3D) routing resource graph, in a subprocess (setup_flow changes the cwd)."""
    sb, il = opts.switch_block_3d, opts.interlayer_delay
    arch_type = opts.architectures[0].type
    is_2d = arch_type == "2d"
    spec = dict(
        original_dir=lazagna_root,
        width=opts.grid.width_2d if is_2d else opts.grid.width_3d,
        height=opts.grid.height_2d if is_2d else opts.grid.height_3d,
        channel_width=opts.grid.channel_width,
        type_sb=arch_type,
        percent_connectivity=sb.connectivity[0],
        place_algorithm=opts.placement.algorithm[0],
        is_verilog_benchmarks=False,
        connection_type=sb.connection_type[0],
        arch_file=arch_path,
        output_additional_info=opts.experiment_name + "_vp_" + str(il.delay_ratio[0]),
        vertical_connectivity=il.vertical_connectivity,
        sb_switch_name=sb.switch_name,
        sb_segment_name=sb.segment_name,
        sb_input_pattern=sb.input_pattern,
        sb_output_pattern=sb.output_pattern,
        sb_location_pattern=sb.location_pattern[0],
        sb_grid_csv_path=sb.grid_csv_path,
        vertical_delay_ratio=il.delay_ratio[0],
        sb_3d_switch_name=sb.switch_name,
        base_delay_switch=il.base_delay_switch,
        switch_interlayer_pairs=il.switch_pairs,
        update_arch_delay=il.update_arch_delay,
        vpr_only=True,
    )
    with tempfile.TemporaryDirectory() as tmp:
        spec["temp_dir"] = tmp
        rc, out = _run([sys.executable, os.path.abspath(__file__), "--setup", json.dumps(spec)],
                       cwd=lazagna_root, timeout_s=timeout_s)
        script = os.path.join(tmp, "task", "designs", "bitstream_script.openfpga")
        if rc != 0 or not os.path.exists(script):
            raise RuntimeError(f"device setup failed (rc={rc}): {out[-1500:]}")
        vpr_line = next(l for l in open(script) if l.startswith("vpr"))
        rrg = re.search(r"--read_rr_graph\s+(\S+)", vpr_line).group(1)
        folder = json.loads(out.strip().splitlines()[-1])["folder"]
        arch_out = os.path.join(folder, "vtr_arch.xml")
        shutil.copy(os.path.join(tmp, "task", "designs", "vtr_arch.xml"), arch_out)
    return {"arch": arch_out, "rrg": rrg, "folder": folder}


def parse_vpr_log(text: str) -> dict:
    d = {"succeeded": "VPR succeeded" in text}
    m = _PLACE_CPD.findall(text) or _PLACE_PERIOD.findall(text)
    d["place_cpd"] = float(m[-1]) * 1e-9 if m else None
    m = _PLACE_WL.findall(text)
    d["place_wl"] = float(m[-1]) if m else None
    m = _ROUTE_CPD.findall(text)
    d["cpd_source"] = "critical_path" if m else None
    if not m:
        m = _ROUTE_PERIOD.findall(text)
        d["cpd_source"] = "geomean_period" if m else None
    d["route_cpd"] = float(m[-1]) * 1e-9 if m else None
    m = _ROUTE_WL.findall(text)
    d["route_wl"] = float(m[-1]) if m else None
    return d


def evaluate(arch_xml: str, opts, blif: str, net: str, seeds, stage: str = "route",
             lazagna_root: str = ".", timeout_s: int = 7200, jobs: Optional[int] = None,
             extra_vpr_options: str = "") -> dict:
    """Evaluate one architecture on one prepared benchmark, all seeds in parallel.

    Returns {"ok", "cpd", "wl", "per_seed": [...], "folder", "error"}. cpd/wl are the
    seed geomeans at the requested fidelity; per_seed carries both the placement estimates
    and (for stage="route") the routed values."""
    assert stage in ("place", "route")
    t0 = time.time()
    arch_hash = hashlib.sha1(arch_xml.encode()).hexdigest()[:12]
    with tempfile.TemporaryDirectory() as tmp:
        arch_path = os.path.join(tmp, f"arch_{arch_hash}.xml")
        with open(arch_path, "w") as f:
            f.write(arch_xml)
        dev = _setup_device(arch_path, opts, lazagna_root, timeout_s)
    t_setup = time.time() - t0

    vpr = os.path.join(lazagna_root, VPR_REL)
    base = [vpr, dev["arch"], blif,
            "--net_file", net, "--verify_file_digests", "off",
            "--route_chan_width", str(opts.grid.channel_width),
            "--place_bounding_box_mode", opts.placement.algorithm[0],
            "--read_rr_graph", dev["rrg"], "--place"]
    if stage == "route":
        base.append("--route")
    extra = (extra_vpr_options + " " + opts.advanced.additional_vpr_options).split()

    def one(seed):
        d = os.path.join(dev["folder"], f"seed_{seed}")
        os.makedirs(d, exist_ok=True)
        # VPR writes its own vpr_stdout.log in the cwd. Console output goes to a DIFFERENT
        # file: two writers on one file interleave lines and corrupt the numbers.
        console = os.path.join(d, "vpr_console.log")
        rc, msg = _run(base + ["--seed", str(seed)] + extra, cwd=d, timeout_s=timeout_s, log_path=console)
        log = os.path.join(d, "vpr_stdout.log")
        if not os.path.exists(log):
            log = console
        text = open(log, errors="ignore").read() if os.path.exists(log) else ""
        r = parse_vpr_log(text)
        r.update(seed=seed, rc=rc, error=None if rc == 0 else (msg or text[-600:]))
        return r

    with ThreadPoolExecutor(max_workers=jobs or len(seeds)) as ex:
        per_seed = list(ex.map(one, seeds))

    key_cpd, key_wl = ("route_cpd", "route_wl") if stage == "route" else ("place_cpd", "place_wl")
    good = [r for r in per_seed if r["rc"] == 0 and r[key_cpd] and r[key_wl]
            and (stage == "place" or r["succeeded"])]
    res = {"ok": len(good) == len(per_seed), "per_seed": per_seed, "folder": dev["folder"],
           "stage": stage, "t_setup_s": round(t_setup, 1), "t_total_s": round(time.time() - t0, 1),
           "cpd": geomean([r[key_cpd] for r in good]) if good else None,
           "wl": geomean([r[key_wl] for r in good]) if good else None,
           "error": None}
    if not res["ok"]:
        bad = [r for r in per_seed if r not in good]
        res["error"] = f"{len(bad)}/{len(per_seed)} seeds failed; first: {bad[0]['error']}"
    with open(os.path.join(dev["folder"], "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--setup":
    spec = json.loads(sys.argv[2])
    sys.path.insert(0, os.path.join(spec["original_dir"], "lazagna"))
    from run_flow import setup_flow
    folder = setup_flow(**spec)
    print(json.dumps({"folder": folder}))
