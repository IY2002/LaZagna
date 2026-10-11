"""
LaZagna YAML Configuration Processor — v2 (Beta)
=================================================

Reads the new hierarchical YAML format (with defaults) and produces
the **exact same** internal parameter combinations as the original
yaml_file_processing.py.  This lets us validate correctness before
migrating the rest of the codebase.

New YAML schema
----------------
  experiment_name     (required)
  grid:               width_3d, height_3d, width_2d, height_2d, channel_width
  architectures:      list of {type, arch_file?}
  benchmarks:         directory, is_verilog
  placement:          algorithm
  seeds:              mode, value
  switch_block_3d:    connectivity, connection_type, switch_name, segment_name,
                      input_pattern, output_pattern, location_pattern,
                      grid_csv_path, custom_patterns?
  interlayer_delay:   vertical_connectivity, delay_ratio, base_delay_switch,
                      update_arch_delay, switch_pairs
  advanced:           additional_vpr_options, vpr_only

Any parameter not provided in the user's YAML is filled from
setup_files/defaults.yaml.

Usage
-----
    from yaml_file_processing_v2 import get_run_params_from_yaml_v2
    combos = get_run_params_from_yaml_v2("path/to/setup.yaml", verbose=True)
"""

import yaml
import copy
import os
import sys
from typing import Dict, List, Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAZAGNA_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DEFAULTS_PATH = os.path.join(LAZAGNA_ROOT, "setup_files", "defaults.yaml")

# ---------------------------------------------------------------------------
# Re-use combination logic from the original processor
# ---------------------------------------------------------------------------
from yaml_file_processing import (
    generate_seed_mapping,
    generate_param_combinations,
    combinations_contains_duplicates,
    print_combinations,
)

# ---------------------------------------------------------------------------
# Built-in default architecture file per switch-block type.
# Used when an architecture entry omits arch_file.
# ---------------------------------------------------------------------------
DEFAULT_ARCH_FILES: Dict[str, str] = {
    "3d_sb":              "{lazagna_root}/arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml",
    "3d_cb":              "{lazagna_root}/arch_files/templates/dsp_bram/vtr_3d_cb_arch_dsp_bram.xml",
    "3d_cb_out_only":     "{lazagna_root}/arch_files/templates/dsp_bram/vtr_3d_cb_out_only_arch_dsp_bram.xml",
    "hybrid_cb":          "{lazagna_root}/arch_files/templates/dsp_bram/vtr_3d_cb_arch_dsp_bram.xml",
    "hybrid_cb_out_only": "{lazagna_root}/arch_files/templates/dsp_bram/vtr_3d_cb_out_only_arch_dsp_bram.xml",
    "2d":                 "{lazagna_root}/arch_files/templates/dsp_bram/vtr_3d_cb_arch_dsp_bram.xml",
}


# ===================================================================
# Helper utilities
# ===================================================================

def deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Recursively merge *override* into *base*.

    - Dict values are merged recursively (so partial overrides of a
      section keep unmentioned sub-keys from the defaults).
    - All other types (lists, scalars) in *override* fully replace
      the corresponding value in *base*.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_defaults() -> Dict:
    """Load the defaults.yaml configuration file."""
    if not os.path.exists(DEFAULTS_PATH):
        raise FileNotFoundError(
            f"Defaults file not found at {DEFAULTS_PATH}.\n"
            f"Please ensure setup_files/defaults.yaml exists."
        )
    with open(DEFAULTS_PATH, "r") as f:
        return yaml.safe_load(f)


# ===================================================================
# Core loader — new format → flat internal dict
# ===================================================================

def load_param_ranges_v2(yaml_file: str) -> Dict:
    """
    Load a v2 hierarchical YAML setup file and convert it into the
    flat internal dictionary that ``generate_param_combinations()``
    expects.  The output structure matches the original
    ``load_param_ranges()`` exactly.
    """

    # ------ load & merge with defaults ------
    with open(yaml_file, "r") as f:
        user_config = yaml.safe_load(f)

    defaults = load_defaults()
    config = deep_merge(defaults, user_config)

    # ------ validate required fields ------
    if "experiment_name" not in config:
        raise ValueError(
            "'experiment_name' is required in every setup file. "
            "Add it to the top level of your YAML."
        )

    # ==============================================================
    # Build the flat params dict (mirrors old load_param_ranges)
    # ==============================================================
    params: Dict[str, Any] = {}

    # -- Grid --
    grid = config.get("grid", {})
    params["width"]         = grid["width_3d"]
    params["height"]        = grid["height_3d"]
    params["width_2d"]      = grid["width_2d"]
    params["height_2d"]     = grid["height_2d"]
    params["channel_width"] = grid["channel_width"]

    # -- Placement --
    placement = config.get("placement", {})
    params["place_algorithm"] = placement["algorithm"]

    # -- Benchmarks --
    benchmarks = config.get("benchmarks", {})
    params["benchmarks_dir"]        = benchmarks["directory"]
    params["is_verilog_benchmarks"] = benchmarks["is_verilog"]

    # -- Switch Block 3D (independent params) --
    sb = config.get("switch_block_3d", {})
    params["percent_connectivity"] = sb["connectivity"]
    params["connection_type"]      = sb["connection_type"]
    params["sb_switch_name"]       = sb["switch_name"]
    params["sb_segment_name"]      = sb["segment_name"]
    params["sb_input_pattern"]     = sb.get("input_pattern", [])
    params["sb_output_pattern"]    = sb.get("output_pattern", [])

    # -- Interlayer Delay --
    delay = config.get("interlayer_delay", {})
    params["vertical_connectivity"]  = delay["vertical_connectivity"]
    params["vertical_delay_ratio"]   = delay["delay_ratio"]
    params["base_delay_switch"]      = delay["base_delay_switch"]
    params["update_arch_delay"]      = delay["update_arch_delay"]
    params["switch_interlayer_pairs"] = delay["switch_pairs"]

    # -- Experiment & Advanced --
    params["cur_loop_identifier"]    = config["experiment_name"]
    advanced = config.get("advanced", {})
    params["additional_vpr_options"] = advanced.get("additional_vpr_options", "")
    params["vpr_only"]               = bool(advanced.get("vpr_only", False))

    # ==============================================================
    # Build linked_params (groups that sweep together)
    # ==============================================================
    params["linked_params"] = {}

    # ---- Architecture type ↔ arch_file ----
    architectures = config.get("architectures", [{"type": "3d_sb"}])
    type_sb_arch_mapping = []
    for arch in architectures:
        arch_type = arch["type"]
        arch_file = arch.get("arch_file", DEFAULT_ARCH_FILES.get(arch_type, ""))
        type_sb_arch_mapping.append(
            {"type_sb": arch_type, "arch_file": arch_file}
        )
    params["linked_params"]["type_sb_arch_mapping"] = type_sb_arch_mapping

    # ---- Seed mapping ----
    seeds = config.get("seeds", {})
    seed_mode  = seeds.get("mode", "fixed")
    seed_value = seeds.get("value", 1)

    if seed_mode == "random":
        params["linked_params"]["seed_mapping"] = generate_seed_mapping(
            int(seed_value)
        )
    elif seed_mode == "list":
        # Explicit seeds, identical across runs, so different architectures are compared
        # on the same placements (paired comparison) instead of fresh random seeds each time.
        params["linked_params"]["seed_mapping"] = [
            {"seed": int(s), "run_num": i}
            for i, s in enumerate(seed_value, 1)
        ]
    else:  # fixed
        params["linked_params"]["seed_mapping"] = [
            {"seed": int(seed_value), "run_num": 1}
        ]

    # ---- Custom SB patterns (linked: input ↔ output) ----
    if "custom_patterns" in sb:
        sb_pattern_mapping = []
        for pattern in sb["custom_patterns"]:
            sb_pattern_mapping.append(
                {
                    "sb_input_pattern": pattern["input"],
                    "sb_output_pattern": pattern["output"],
                }
            )
        params["linked_params"]["sb_pattern_mapping"] = sb_pattern_mapping
        # Remove from top level — they come from linked_params instead
        params.pop("sb_input_pattern", None)
        params.pop("sb_output_pattern", None)

    # ---- Location pattern (linked: location ↔ csv_path) ----
    location_patterns = sb.get("location_pattern", ["repeated_interval"])
    grid_csv_path     = sb.get("grid_csv_path", "")

    params["linked_params"]["sb_location_pattern"] = []
    for location in location_patterns:
        if location == "custom":
            if isinstance(grid_csv_path, list):
                for csv_path in grid_csv_path:
                    params["linked_params"]["sb_location_pattern"].append(
                        {
                            "sb_location_pattern": location,
                            "sb_grid_csv_path": csv_path.replace(
                                "{lazagna_root}", LAZAGNA_ROOT
                            ),
                        }
                    )
            elif grid_csv_path:
                params["linked_params"]["sb_location_pattern"].append(
                    {
                        "sb_location_pattern": location,
                        "sb_grid_csv_path": grid_csv_path.replace(
                            "{lazagna_root}", LAZAGNA_ROOT
                        ),
                    }
                )
            else:
                params["linked_params"]["sb_location_pattern"].append(
                    {"sb_location_pattern": location, "sb_grid_csv_path": ""}
                )
        else:
            params["linked_params"]["sb_location_pattern"].append(
                {"sb_location_pattern": location, "sb_grid_csv_path": ""}
            )

    return params


# ===================================================================
# Public entry point
# ===================================================================

def get_run_params_from_yaml_v2(
    file_path: str, verbose: bool = False
) -> List[Dict]:
    """
    Load a v2 YAML setup file, generate all parameter combinations,
    and apply the same cleanup / filtering rules as the original
    ``get_run_params_from_yaml()``.
    """

    params = load_param_ranges_v2(file_path)

    # Replace {lazagna_root} in benchmarks_dir (matches v1 behaviour)
    if "benchmarks_dir" in params:
        params["benchmarks_dir"] = params["benchmarks_dir"].replace(
            "{lazagna_root}", LAZAGNA_ROOT
        )

    # Generate all combinations (reuses the original Cartesian-product logic)
    combinations = generate_param_combinations(params)

    if combinations_contains_duplicates(combinations):
        if verbose:
            print("Warning: Duplicate combinations found!")

    # ---- Cleanup: identical rules to the original processor ----
    cleaned_combinations: List[Dict] = []
    for combo in combinations:
        # Skip invalid: 2d/3d_cb/3d_cb_out_only with non-subset connection
        if (
            combo["type_sb"] in ["2d", "3d_cb", "3d_cb_out_only"]
            and combo["connection_type"] != "subset"
        ):
            continue

        # Skip invalid: 2d with non-cube_bb placement
        if combo["type_sb"] == "2d" and combo["place_algorithm"] != "cube_bb":
            continue

        # Skip invalid: 2d/3d_cb/3d_cb_out_only with partial connectivity
        if (
            combo["type_sb"] in ["2d", "3d_cb", "3d_cb_out_only"]
            and combo["percent_connectivity"] != 1.0
        ):
            continue

        # Use 2D grid dimensions for the "2d" type
        if combo["type_sb"] == "2d":
            combo["height"] = combo["height_2d"]
            combo["width"]  = combo["width_2d"]

        del combo["width_2d"]
        del combo["height_2d"]

        # Append delay ratio to experiment identifier
        combo["cur_loop_identifier"] = (
            combo["cur_loop_identifier"]
            + "_vp_"
            + str(combo["vertical_delay_ratio"])
        )

        cleaned_combinations.append(combo)

    if verbose:
        print(f"\nNumber of combinations: {len(cleaned_combinations)}")
        print_combinations(cleaned_combinations)

    return cleaned_combinations


# ===================================================================
# Comparison utility — verify v2 matches v1
# ===================================================================

def compare_outputs(
    v1_combos: List[Dict],
    v2_combos: List[Dict],
    label: str = "",
) -> bool:
    """
    Element-by-element comparison of two lists of combination dicts.
    Returns True if every combination matches.
    """
    prefix = f"[{label}] " if label else ""

    if len(v1_combos) != len(v2_combos):
        print(
            f"{prefix}❌ COUNT MISMATCH: "
            f"v1 produced {len(v1_combos)}, v2 produced {len(v2_combos)}"
        )
        return False

    all_match = True
    for i, (c1, c2) in enumerate(zip(v1_combos, v2_combos)):
        if c1 != c2:
            all_match = False
            print(f"{prefix}❌ MISMATCH in combination {i + 1}:")
            all_keys = sorted(set(c1.keys()) | set(c2.keys()))
            for key in all_keys:
                v1_val = c1.get(key, "<MISSING>")
                v2_val = c2.get(key, "<MISSING>")
                if v1_val != v2_val:
                    print(f"    {key}:")
                    print(f"      v1: {v1_val}")
                    print(f"      v2: {v2_val}")

    if all_match:
        print(f"{prefix}✅ MATCH — {len(v1_combos)} combination(s) identical")

    return all_match


# ===================================================================
# Self-test: compare v1 (old YAML) ↔ v2 (new YAML) for every test
# ===================================================================

if __name__ == "__main__":
    from yaml_file_processing import get_run_params_from_yaml

    setup_dir = os.path.join(LAZAGNA_ROOT, "setup_files")

    test_pairs = [
        ("v1_backup/simple_test.yaml",              "simple_test.yaml"),
        ("v1_backup/connectivity_type_test.yaml",   "connectivity_type_test.yaml"),
        ("v1_backup/sb_percentage_test.yaml",       "sb_percentage_test.yaml"),
        ("v1_backup/sb_pattern_test.yaml",          "sb_pattern_test.yaml"),
        ("v1_backup/verilog_benchmark_test.yaml",   "verilog_benchmark_test.yaml"),
        ("v1_backup/sb_locations_test.yaml",        "sb_locations_test.yaml"),
        ("v1_backup/vertical_delay_test.yaml",      "vertical_delay_test.yaml"),
    ]

    all_pass = True
    for old_name, new_name in test_pairs:
        old_path = os.path.join(setup_dir, old_name)
        new_path = os.path.join(setup_dir, new_name)

        if not os.path.exists(old_path):
            print(f"⚠  Skipping {old_name}: old v1 file not found")
            continue
        if not os.path.exists(new_path):
            print(f"⚠  Skipping {new_name}: new file not found")
            continue

        v1_result = get_run_params_from_yaml(old_path, verbose=False)
        v2_result = get_run_params_from_yaml_v2(new_path, verbose=False)

        if not compare_outputs(v1_result, v2_result, label=old_name):
            all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("ALL TESTS PASSED ✅")
    else:
        print("SOME TESTS FAILED ❌")

    sys.exit(0 if all_pass else 1)
