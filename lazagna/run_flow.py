import subprocess
import tempfile
import os
import time
from arch_xml_modification import *
from file_handling import *
from script_editing import *
from printing import print_verbose
import shutil
import sys

and2_blif_path = "/benchmarks/and2/and2.blif"

def run_command_in_temp_dir(command, original_dir, handle_error=True, verbose=False):
    """
    Run a command in a temporary directory.
    
    Args:
        command (list): Command to execute
        original_dir (str): Original working directory
    
    Returns:
        subprocess.CompletedProcess: Result of the command execution
    """
    if verbose:
        print_verbose("Running Command: ")
        command_string = " ".join(command)
        print_verbose(f"{command_string}")
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temporary_dir:
        try:
            # Change to the temporary directory
            os.chdir(temporary_dir)
            
            # Execute the command
            result = subprocess.run(command, 
                                  capture_output=True,
                                  text=True,
                                  check=True)
            if verbose:
                print_verbose("Command output:")
                print_verbose(result.stdout)
            
            return result
            
        except subprocess.CalledProcessError as e:
            if verbose:
                print_verbose(f"Command failed with error code {e.returncode}")
                print_verbose("Error output:")
                print_verbose(e.stdout)
                print_verbose(e.stderr)
            if handle_error:
                raise
        except FileNotFoundError:
            print_verbose(os.getcwd())
            print_verbose("Command not found. Please check the path and permissions.")
            raise
        finally:
            # Always change back to the original directory
            os.chdir(original_dir)

def run_task(original_dir, temp_dir=""):

    run_command = ["python3",
               original_dir + "/OpenFPGA/openfpga_flow/scripts/run_fpga_task.py",
               temp_dir]
    
    run_command_in_temp_dir(run_command, original_dir, handle_error=False, verbose=False)

def run_flow(original_dir, width, height, channel_width, benchmark_name="", temp_dir ="", type_sb="full", arch_path="", rrg_3d_path="", percent_connectivity=0.5, place_algorithm="cube_bb", connection_type="subset", run_num=1, output_additional_info=""):
    print_verbose(f"Temp Dir for benchmark {benchmark_name}: {temp_dir}")

    start_time = time.time()
    run_task(original_dir, temp_dir)
    end_time = time.time()

    run_time = (end_time - start_time) * 1000
    print_verbose(f"Running OpenFPGA task for benchmark {benchmark_name} took {run_time:0.2f} ms")

    # Now copy results into somewhere else maybe?
    # Feels a bit sketch should automate it so the reuslts are auto placed into nice named area but oh well
    task_result_path = "/run001/task_result.csv"
    results_path = "/results/3d_" + type_sb + "_cw_" + output_file_name(channel_width=channel_width, width=width, height=height, percent_connectivity=percent_connectivity, place_algorithm=place_algorithm, connection_type=connection_type, run_num=run_num, additional_info=output_additional_info) + "/"
    result_file_name = benchmark_name + "_results_cw_" + output_file_name(channel_width=channel_width, width=width, height=height, percent_connectivity=percent_connectivity, place_algorithm=place_algorithm, connection_type=connection_type, run_num=run_num, additional_info=output_additional_info) + ".csv"

    print_verbose(f"Trying to copy for benchmark {benchmark_name} the results to {original_dir + results_path + result_file_name} from {temp_dir + task_result_path}")

    # Make sure the results directory exists
    os.makedirs(original_dir + "/results", exist_ok=True)

    if os.path.exists(temp_dir + task_result_path):
        start_time = time.time()
        copy_results(original_dir, task_result_path, results_path, result_file_name, temp_dir)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Copying the results for benchmark {benchmark_name} to {original_dir + results_path + result_file_name} took {run_time:0.2f} ms")
    else:
        start_time = time.time()
        generate_empty_results(original_dir, results_path, result_file_name, benchmark_name)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Generating Empty Results file and writing to {original_dir + results_path + result_file_name} took {run_time:0.2f} ms")

def setup_flow(original_dir, width, height, channel_width, type_sb="full", percent_connectivity=0.5, place_algorithm="cube_bb", is_verilog_benchmarks=False, connection_type="subset", arch_file="", random_seed=1, run_num=1, extra_vpr_options="", output_additional_info="", temp_dir="", vertical_connectivity=1, sb_switch_name="", sb_segment_name="", sb_input_pattern=[], sb_output_pattern=[], sb_location_pattern="repeated_interval", sb_grid_csv_path="", vertical_delay_ratio=1, sb_3d_switch_name="3D_SB_switch", base_delay_switch="", switch_interlayer_pairs={}, update_arch_delay=False, vpr_only=False):
    

    # Copy the task directory to the temp directory and work on it from there
    shutil.copytree(original_dir + "/task", temp_dir + "/task", dirs_exist_ok=True)

    # copy template script to designs
    # TODO: This is a bit sketchy, should make it more robust in the future to allow for multiple arch runs at the same time, no hard coding values
    script_template = "vpr_only_script_template.openfpga" if vpr_only else "bitstream_script_template.openfpga"
    command = ["cp", temp_dir + "/task/config_templates/" + script_template, temp_dir + "/task/designs/bitstream_script.openfpga"]
    run_command_in_temp_dir(command, original_dir)

    script_path ="/designs/bitstream_script.openfpga"

    # Set the base arch file and output directory based on the type of switch block
    # Base arch layout will be modified to have the correct dimensions and then saved to the output directory
    if type_sb == "3d_cb":
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_3d_cb_arch.xml"
        arch_output_dir = original_dir + "/arch_files/3d_cb_arch/"
    elif type_sb == "2d":
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_2d_arch.xml"
        arch_output_dir = original_dir + "/arch_files/2d_arch/" 
    elif type_sb == "3d_cb_out_only":
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_3d_cb_out_only_arch.xml"
        arch_output_dir = original_dir + "/arch_files/3d_cb_arch/" 
    elif type_sb == "hybrid_cb":
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_3d_cb_arch.xml"
        arch_output_dir = original_dir + "/arch_files/3d_cb_arch/vtr_3d_hybrid_cb_arch_" + str(width) + "x" + str(height) + ".xml"
    elif type_sb == "hybrid_cb_out":
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_3d_cb_out_only_arch.xml"
        arch_output_dir = original_dir + "/arch_files/3d_cb_arch/vtr_3d_hybrid_cb_out_arch_" + str(width) + "x" + str(height) + ".xml"
    else:
        arch_base_file = original_dir + "/arch_files/templates/basic/vtr_arch.xml"
        arch_output_dir = original_dir + "/arch_files/3d_arch/"
    
    if arch_file != "":
        arch_base_file = arch_file
        arch_output_dir = original_dir + "/arch_files/" 
    
    delay_ratio_string = ""
    if update_arch_delay:
        delay_ratio_string = "_delay_ratio_" + str(vertical_delay_ratio)

    arch_output_file_name = os.path.splitext(os.path.basename(arch_base_file))[0] + "_" + str(width) + "x" + str(height) + delay_ratio_string + ".xml"

    arch_output_file_path = arch_output_dir + arch_output_file_name

    # Check if the modified Arch XML already exists, if not make it
    if not os.path.exists(original_dir + arch_output_file_path):
        start_time = time.time()
        tree, root = load_xml(arch_base_file)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Loading Base Arch XML took {run_time:0.2f} ms")

        start_time = time.time()
        set_fixed_layout_dimensions(root, width=width, height=height)

        if update_arch_delay:
            update_vertical_delay_ratio(root, vertical_delay_ratio=vertical_delay_ratio, sb_3d_switch_name=sb_3d_switch_name, base_delay_switch=base_delay_switch, switch_interlayer_pairs=switch_interlayer_pairs)

        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Modifiying Base Arch XML took {run_time:0.2f} ms")

        start_time = time.time()
        save_xml(tree, arch_output_file_path)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Saving the modified Arch XML took {run_time:0.2f} ms")
    else:
        print_verbose(f"Modified Arch XML previously generated")
    
    # copy the modified arch file into the task
    # TODO: This is a bit sketchy, should make it more robust in the future to allow for multiple arch runs at the same time, no hard coding values
    command = ["cp", arch_output_file_path, temp_dir + "/task/designs/vtr_arch.xml"]
    run_command_in_temp_dir(command, original_dir)

    relative_arch_path = os.path.relpath(arch_output_file_path, original_dir)
    relative_arch_path = "/" + relative_arch_path

    start_time = time.time()
    append_cw_to_script(temp_dir + "/task" + script_path, str(channel_width))
    end_time = time.time()

    run_time = (end_time - start_time) * 1000
    print_verbose(f"Adding Channel Width to execution script took {run_time:0.2f} ms")

    start_time = time.time()
    append_place_algorithm_to_script(temp_dir + "/task" + script_path, place_algorithm)
    end_time = time.time()

    run_time = (end_time - start_time) * 1000
    print_verbose(f"Adding Placement Algorithm to execution script took {run_time:0.2f} ms")

    rrg_path = "/base_rrg/rrg_cw_" + str(channel_width) + "_" + arch_output_file_name

    vertical_connectivity_string = "vp_" + str(vertical_connectivity) + "_"
    if vertical_connectivity == 1:
        vertical_connectivity_string = ""

    sb_pattern_string = ""

    # if the connection type is custom, add its pattern to the path
    if connection_type == "custom":
        if sb_input_pattern != []:
            sb_input_pattern = [str(x) for x in sb_input_pattern]
            sb_pattern_string = "_input_" + "_".join(sb_input_pattern)
        else:
            print("ERROR: No input pattern provided for custom connection type.")
            exit(1)

        if sb_output_pattern != []:
            sb_output_pattern = [str(x) for x in sb_output_pattern]
            sb_pattern_string += "_output_" + "_".join(sb_output_pattern)
        else:
            print("ERROR: No output pattern provided for custom connection type.")
            exit(1)

    # if the location pattern is custom, add its pattern to the path
    if sb_location_pattern != "repeated_interval":
        if sb_location_pattern == "custom":
            if sb_grid_csv_path == "":
                print("ERROR: No custom SB grid CSV path provided.")
                exit(1)
            else:
                sb_pattern_string += "_" + sb_location_pattern + "_" + os.path.splitext(os.path.basename(sb_grid_csv_path))[0]
        else:
            sb_pattern_string += "_" + sb_location_pattern

    rrg_3d_path = "/rrg_3d/rrg_3d_" + type_sb + "_cw_" + str(channel_width) + "_" + str(int(percent_connectivity * 100)) + "percent_" + connection_type + sb_pattern_string + "_" + vertical_connectivity_string + arch_output_file_name

    # if base rrg does not exist, create it (AKA run VTR)
    if not os.path.exists(original_dir + rrg_path):
        start_time = time.time()
        create_base_rrg(original_dir, relative_arch_path, channel_width=channel_width, path_to_write_rrg=rrg_path)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Generating Base RRG took {run_time:0.2f} ms")
    else:
        print_verbose(f"Base RRG previously generated at {original_dir + rrg_path}")

    # if 3d rrg does not exist, create it
    if not os.path.exists(original_dir + rrg_3d_path) and type_sb != "3d_cb" and type_sb != "2d" and type_sb != "3d_cb_out_only":
        start_time = time.time()
        create_custom_3d_rrg(rrg_path, rrg_3d_path, original_dir, percent_connectivity, connection_type, arch_file=arch_base_file, vertical_connectivity=vertical_connectivity, sb_switch_name=sb_switch_name, sb_segment_name=sb_segment_name, sb_input_pattern=sb_input_pattern, sb_output_pattern=sb_output_pattern, sb_location_pattern=sb_location_pattern, sb_grid_csv_path=sb_grid_csv_path)
        end_time = time.time()

        run_time = (end_time - start_time) * 1000
        print_verbose(f"Generating 3D RRG from Base RRG took {run_time:0.2f} ms")    
    else:
        if type_sb == "3d_cb" or type_sb == "2d" or type_sb == "3d_cb_out_only":
            print_verbose(f"3D RRG not generated since type {type_sb} does not need a custom RRG, using base RRG")
        else:
            print_verbose(f"3D RRG previously generated at {original_dir + rrg_3d_path}")

    if type_sb == "3d_cb" or type_sb == "2d" or type_sb == "3d_cb_out_only":
        # Copy Base RRG path into task script (only need base since 3D SBs are not used)
        append_rrg_to_script(temp_dir + "/task" + script_path, original_dir + rrg_path)

    else:
        # Copy 3D RRG path into task script
        append_rrg_to_script(temp_dir + "/task" + script_path, original_dir + rrg_3d_path)



    if is_verilog_benchmarks:
        # TODO: This is a bit sketchy, should make it more robust in the future to allow for multiple arch runs at the same time, no hard coding values
        command = ["cp", temp_dir + "/task/config_templates/verilog_task.conf", temp_dir + "/task/config/task.conf"]
        run_command_in_temp_dir(command, original_dir)
    else:
        # TODO: This is a bit sketchy, should make it more robust in the future to allow for multiple arch runs at the same time, no hard coding values
        command = ["cp", temp_dir + "/task/config_templates/blif_task.conf", temp_dir + "/task/config/task.conf"]
        run_command_in_temp_dir(command, original_dir)

    #append random seed to script
    append_random_seed_to_script(temp_dir + "/task" + script_path, random_seed)

    #append extra vpr options to script
    if extra_vpr_options != "":
        append_extra_vpr_option_to_script(temp_dir + "/task" + script_path, extra_vpr_options)

    # Make tasks_run directory
    #Output folder name based on parameters and time of run
    curr_time = time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime())
    folder_name = "3d_" + type_sb + "_cw_" + output_file_name(channel_width=channel_width, width=width, height=height, percent_connectivity=percent_connectivity, place_algorithm=place_algorithm, connection_type=connection_type, run_num=run_num, additional_info=output_additional_info) + "_" + curr_time
    os.makedirs(original_dir + "/tasks_run/" + folder_name, exist_ok=True)
    return original_dir + "/tasks_run/" + folder_name

def create_base_rrg(original_dir:str, path_to_arch:str, channel_width=2, path_to_write_rrg="/base_rrg/rr_graph.xml", path_to_benchmark=and2_blif_path):
    
    # Make sure the output directory exists
    os.makedirs(os.path.dirname(original_dir + path_to_write_rrg), exist_ok=True)

    command = [original_dir + "/OpenFPGA/build/vtr-verilog-to-routing/vpr/vpr", 
                      original_dir + path_to_arch, 
                      original_dir + path_to_benchmark, 
                      "--route_chan_width", 
                      str(channel_width), 
                      "--write_rr_graph", 
                      original_dir + path_to_write_rrg,
                      "--clock_modeling",
                      "route",
                      "--pack"]
    
    print_verbose(f"Creating Base RRG with command: {' '.join(command)}")
    
    run_command_in_temp_dir(command, original_dir, handle_error=False, verbose=False)

def create_custom_3d_rrg(base_arch_path, output_file_path, original_dir, percent_connectivity=0.5, connection_type="subset", arch_file ="", vertical_connectivity=1, sb_switch_name="", sb_segment_name="", sb_input_pattern=[], sb_output_pattern=[], sb_location_pattern="repeated_interval", sb_grid_csv_path=""):

    # Make sure the output directory exists
    os.makedirs(os.path.dirname(original_dir + output_file_path), exist_ok=True)

    command = ["python3", 
               original_dir + "/scripts/3d_sb_creator.py",
               "-f", original_dir + base_arch_path,
               "-o", original_dir + output_file_path,
               "-p", str(percent_connectivity),
               "-c", connection_type,
               "-a", arch_file,
               "-vp", str(vertical_connectivity),
               "--sb_location_pattern", sb_location_pattern,]

    sb_grid_csv_string = ""

    if sb_location_pattern == "custom":
        if sb_grid_csv_path == "":
            print("ERROR: No custom SB grid CSV path provided.")
            exit(1)
        else:

            command.append("--sb_grid_csv")
            command.append(sb_grid_csv_path)

    sb_input_pattern_string = ""
    sb_output_pattern_string = ""

    if connection_type == "custom":
        if sb_input_pattern != []:
            sb_input_pattern = [str(x) for x in sb_input_pattern]
            command.append("--sb_input_pattern")
            for x in sb_input_pattern:
                command.append(str(x))
        else:
            print("ERROR: No input pattern provided for custom connection type.")
            exit(1)
        
        if sb_output_pattern != []:
            sb_output_pattern = [str(x) for x in sb_output_pattern]
            command.append("--sb_output_pattern")
            for x in sb_output_pattern:
                command.append(str(x))
        else:
            print("ERROR: No output pattern provided for custom connection type.")
            exit(1)


    if sb_switch_name != "":
        command.append("--sb_3d_switch")
        command.append(sb_switch_name)

    if sb_segment_name != "":
        command.append("--sb_3d_segment")
        command.append(sb_segment_name)

    
    run_command_in_temp_dir(command, original_dir, verbose=True)

def copy_results(original_dir, task_result_path, results_path, result_name, temp_dir=""):
        
    os.makedirs(os.path.dirname(original_dir + results_path), exist_ok=True)

    command = ["cp",
               temp_dir + task_result_path, 
               original_dir + results_path + result_name]
    
    run_command_in_temp_dir(command, original_dir)
