# Main scripting file to run LaZagna

from run_interface import run_interface, ITD_paper_top_modules, ITD_subset_top_modules, ITD_quick_top_modules, VTR_benchmarks_top_modules
from file_handling import get_files_with_extension
from yaml_file_processing_v2 import get_run_params_from_yaml_v2
import os
from concurrent.futures import ProcessPoolExecutor
import psutil
import printing
import time
import argparse

eltwise_top_modules = {"eltwise_layer.v" :"eltwise_layer"}

parser = argparse.ArgumentParser(description="Run 3DFADE tests in parallel using configurations in a yaml file.")

parser.add_argument("-f", "--yaml_file", type=str, required=True, help="Path to the yaml file containing the test parameters.")
parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
parser.add_argument("-j", "--num_workers", type=int, default=1, help="Number of parallel workers to use. Default is 1. Total number of cores = <num_workers> * <num_task_workers>")
parser.add_argument("-n", "--num_task_workers", type=int, default=1, help="Number of parallel workers to use per task. Default is 1. Total number of cores = <num_workers> * <num_task_workers>")
# the directory of this file
original_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run_job(param):
    # Lower the priority of the current process
    process = psutil.Process(os.getpid())
    process.nice(11)
    
    param_copy = param.copy()
    param_copy['original_dir'] = original_dir
    param_copy['num_task_workers'] = param.get('num_task_workers', 1)
    return run_interface(params=param_copy)

def setup_benchmark_files(run_params):
    for param in run_params:
        is_verilog_benchmarks = param.get("is_verilog_benchmarks", False)
        benchmarks_dir = param.get("benchmarks_dir", original_dir + "/benchmarks/MCNC_benchmarks")

        if is_verilog_benchmarks and benchmarks_dir == original_dir + "/benchmarks/ITD_paper":
            top_module_names = ITD_paper_top_modules
        elif is_verilog_benchmarks and benchmarks_dir == original_dir + "/benchmarks/VTR_benchmarks":
            top_module_names = VTR_benchmarks_top_modules
        elif is_verilog_benchmarks and benchmarks_dir == original_dir + "/benchmarks/ITD_subset":
            top_module_names = ITD_subset_top_modules
        elif is_verilog_benchmarks and benchmarks_dir == original_dir + "/benchmarks/ITD_quick":
            top_module_names = ITD_quick_top_modules
        elif is_verilog_benchmarks and benchmarks_dir == original_dir + "/benchmarks/eltwise":
            top_module_names = eltwise_top_modules
        else:
            # Single-design or custom dirs: look the top module up by file name across every
            # known suite (VTR designs often name their top differently from the file).
            top_module_names = {**ITD_paper_top_modules, **ITD_subset_top_modules,
                                **ITD_quick_top_modules, **VTR_benchmarks_top_modules,
                                **eltwise_top_modules}

        if is_verilog_benchmarks:
            blif_files = get_files_with_extension(benchmarks_dir, ".v")
            verilog_files = get_files_with_extension(benchmarks_dir, ".v")
            act_files = get_files_with_extension(benchmarks_dir, ".v")

        else:
            blif_files = get_files_with_extension(benchmarks_dir, ".blif")
            verilog_files = get_files_with_extension(benchmarks_dir, ".v")
            act_files = get_files_with_extension(benchmarks_dir, ".act")

        param['blif_files'] = blif_files
        param['verilog_files'] = verilog_files
        param['act_files'] = act_files
        param['top_module_names'] = top_module_names

    return run_params


def main():

    start_time = time.time()

    args = parser.parse_args()
    yaml_file = args.yaml_file
    verbose = args.verbose

    # only enable false for debugging, it prints too much, give out every formation tested.
    run_params = get_run_params_from_yaml_v2(yaml_file, verbose=False)

    run_params = setup_benchmark_files(run_params)

    printing.verbose = verbose

    num_workers = args.num_workers

    print(f"Running {len(run_params)} jobs in parallel using {num_workers} workers")
        
    num_task_workers = args.num_task_workers
    for param in run_params:
        param['num_task_workers'] = num_task_workers
    
    # Run jobs in parallel using ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(run_job, run_params))

    end_time = time.time()

    elapsed_time = (end_time - start_time) * 1000
    print(f"time to run tests: {elapsed_time:.2f} ms")

if __name__ == "__main__":
    main()
