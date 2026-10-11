import os
from lxml import etree
import csv

def load_xml(file_path):
    """Load an XML file and return the tree and root elements."""
    tree = etree.parse(file_path)
    root = tree.getroot()
    return tree, root

def save_xml(tree, file_path):
    """Save the XML tree to a file."""

    # Make sure the directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    tree.write(file_path, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def generate_empty_results(original_dir, result_path, result_file_name, benchmark_name):
    csv_headers = ["name", "TotalRunTime", "average_net_length", "clb_blocks", "critical_path", "io_blocks", "packing_time", "placement_time", "routing_time", "total_logic_block_area", "total_routing_area", "total_routing_time", "total_wire_length"]
    csv_results = ["00_" + benchmark_name + "_Common", 0,0,0,0,0,0,0,0,0,0,0,0]

    os.makedirs(os.path.dirname(original_dir + result_path), exist_ok=True)

    with open(original_dir + result_path + result_file_name, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(csv_headers)  # Write headers
        writer.writerow(csv_results)  # Write data

def get_files_with_extension(directory, extension):
    """
    Recursively finds all files with the '.blif' extension in the given directory.
    
    Args:
        directory (str): The path to the directory to search.
        
    Returns:
        list: A list of full paths to each '.blif' file.
    """
    blif_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(extension):
                blif_files.append(os.path.join(root, file))
    return blif_files

def extract_file_name(file_path):
    base_name = os.path.basename(file_path)
    name_without_extension = os.path.splitext(base_name)[0]
    return name_without_extension

def output_file_name(channel_width, width, height, percent_connectivity, place_algorithm,  connection_type, run_num=1, additional_info=""):
    return str(channel_width) + "_" + str(width) + "x" + str(height) + "_" + str(int(percent_connectivity * 100)) + "percent_" + place_algorithm + "_" + connection_type + "_" + additional_info.replace(" ", "_") + "_run" + str(run_num)

# Simulation models of VTR hard primitives that VTR's benchmark files carry (often pasted at
# the end of the file, marked keep_hierarchy). They are never the design's top module.
VTR_PRIMITIVE_MODULES = {"single_port_ram", "dual_port_ram", "mult", "adder", "multiply"}

def infer_top_module(verilog_path, fallback=None):
    """Top module of a Verilog file: the module no other module instantiates.

    Ignores comments and VTR primitive models. If several candidates remain, prefers the
    one matching the file name, then the largest. Returns `fallback` if nothing is found."""
    import re
    try:
        text = open(verilog_path, errors="ignore").read()
    except OSError:
        return fallback
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    bodies = {}
    for m in re.finditer(r"\bmodule\s+(\w+)(.*?)\bendmodule\b", text, re.S):
        bodies.setdefault(m.group(1), m.group(2))
    names = set(bodies) - VTR_PRIMITIVE_MODULES
    used = set()
    for body in bodies.values():
        for n in names:
            if n not in used and re.search(r"(^|[;\s])" + re.escape(n) + r"(?!\w)\s*(#|\w)", body):
                used.add(n)
    tops = [n for n in names if n not in used]
    if not tops:
        return fallback
    stem = os.path.splitext(os.path.basename(verilog_path))[0]
    if stem in tops:
        return stem
    return max(tops, key=lambda n: len(bodies[n]))
