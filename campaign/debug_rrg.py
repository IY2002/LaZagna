# Reproduce 3d_sb_creator failures for structured layouts and print the creator's own stderr.
import os, sys, subprocess, json, glob, re, tempfile
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna"); CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work"); os.chdir(ROOT); sys.path[:0] = [CODE, ROOT, ROOT + "/lazagna"]
from lazagna_optuna import SearchConfig, autosize, structured_columns, column_counts, build_architecture, _template
from run_flow import create_base_rrg
from arch_xml_modification import set_fixed_layout_dimensions
J = sorted(glob.glob(WORK + "/journal/*attention*.log"))[0]
# collect params of pruned trials from the journal (op 5 = set params; state 2 = pruned)
params, states = {}, {}
for l in open(J):
    o = json.loads(l)
    tid = o.get("trial_id")
    if o.get("op_code") == 5 or "param_name" in o:
        params.setdefault(tid, {})[o["param_name"]] = o["param_value_internal"]
    if "state" in o and tid is not None:
        states[tid] = o["state"]
bad = [params[t] for t, s in states.items() if s == 2 and len(params.get(t, {})) >= 5][:3]
good = [params[t] for t, s in states.items() if s == 1 and len(params.get(t, {})) >= 5][:2]
print("pruned examples:", bad); print("complete examples:", good)
base = SearchConfig(lazagna_root=ROOT, benchmark_dir=WORK + "/bench/cols_attention_layer", is_verilog=True,
                    arch_type="combined", search_mode="structured", prep_dir="/prep",
                    template_path="arch_files/templates/dsp_bram_tall/vtr_arch_dsp_bram.xml",
                    template_2d_path="arch_files/templates/dsp_bram_tall/vtr_2d_arch_dsp_bram.xml")
cfg, _ = autosize(base)
n = cfg.width - 2; _, nd, nb = column_counts(cfg)
os.makedirs(WORK + "/dbg", exist_ok=True)
for tag, p in [("bad%d" % i, x) for i, x in enumerate(bad)] + [("good%d" % i, x) for i, x in enumerate(good)]:
    # internal repr: ints as floats
    spec = structured_columns(n, nd, nb, int(p["dsp_on_l0"]), int(p["bram_on_l0"]), p["cluster"], p["stagger"], p["band_pos"])
    print(tag, "".join({'clb':'.','dsp':'D','bram':'B'}[c] for c in spec.columns[0]), "|",
          "".join({'clb':'.','dsp':'D','bram':'B'}[c] for c in spec.columns[1]))
    arch = build_architecture(spec, cfg.width, cfg.height, _template(cfg, False))
    ap = f"{WORK}/dbg/{tag}.xml"; open(ap, "w").write(arch)
    rrg = f"/base_rrg/dbg_{tag}.xml"
    create_base_rrg(ROOT, "/../.." + ap, channel_width=300, path_to_write_rrg=rrg)  # it prepends ROOT
    r = subprocess.run(["python3", ROOT + "/scripts/3d_sb_creator.py", "-f", ROOT + rrg, "-o", f"{WORK}/dbg/{tag}_3d.xml",
                        "-p", "1.0", "-c", "subset", "-a", ap, "-vp", "1", "--sb_location_pattern", "repeated_interval",
                        "--sb_3d_switch", "3D_SB_switch", "--sb_3d_segment", "3D_SB_connection"], capture_output=True, text=True)
    print(tag, "rc", r.returncode); print((r.stderr or r.stdout)[-1500:])
