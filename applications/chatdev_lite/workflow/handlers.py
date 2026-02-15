from datetime import datetime
import logging
import os
import shutil
import time
import numpy as np

from applications.chatdev_lite.workflow.utils import get_config
from applications.chatdev_lite.chatdev.utils import log_visualize, now

config_path, config_phase_path, config_role_path = get_config()

def pre_processing(message:dict, attributes:dict[str,object]) -> dict:
    """
    Remove unnecessary files and log global configurations.
    """
    filepath = os.path.dirname(os.path.dirname(__file__))
    directory = os.path.join(filepath, "assets/output/WareHouse")
    
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path) and not filename.endswith(".py") and not filename.endswith(".log"):
            try:
                os.remove(file_path)
            except Exception as e:
                pass

    software_path = os.path.join(directory,
                                 f"{attributes['project_name']}_{attributes['org_name']}_{attributes['start_time']}")
    set_directory(software_path,attributes)

    # Override GUI setting: use text-based prompts instead of graphical interface, but keep main.py as entry point
    attributes['gui'] = "The software should interact with the user through command-line text prompts, without using a graphical user interface (GUI). The entry point should be the specified function in the designated file, or `main` if no specific entry point is provided, with all functionalities ideally contained within a single file."
    # attributes['gui'] = "The software should interact with the user through command-line text prompts, without using a graphical user interface (GUI). The entry point should be the specified function in the designated file, with all functionalities ideally contained within a single file."

    from applications.chatdev_lite.components.tools import RuntimeContext, set_runtime
    set_runtime(RuntimeContext(
        directory=attributes.get("directory"),
        code_manager=attributes.get("code_manager"),
        requirement_manager=attributes.get("requirement_manager"),
        manual_manager=attributes.get("manual_manager"),
        git_management=attributes.get("git_management", False),
        attributes=attributes
    ))

    os.makedirs(software_path, exist_ok=True)

    try:
        shutil.copy(config_path, software_path)
        shutil.copy(config_phase_path, software_path)
        shutil.copy(config_role_path, software_path)
    except FileNotFoundError as e:
        pass

    try:
        with open(os.path.join(software_path, f"{attributes['project_name']}.prompt"), "w") as f:
            f.write(attributes['task'])
    except Exception as e:
        print(f"Error writing task prompt: {e}")

    preprocess_msg = "**[Preprocessing]**\n\n"
    preprocess_msg += f"**ChatDev Starts** ({attributes['start_time']})\n\n"
    preprocess_msg += f"**Timestamp**: {attributes['start_time']}\n\n"
    preprocess_msg += f"**task_prompt**: {attributes['task']}\n\n"
    preprocess_msg += f"**project_name**: {attributes['project_name']}\n\n"
    preprocess_msg += f"**Log File**: {attributes['log_filepath']}\n\n"
    preprocess_msg += f"**ChatGPTConfig**:\n{attributes['model_name']}\n\n"
    preprocess_msg += f"**gui**: {attributes['gui']}\n\n"
    log_visualize(preprocess_msg)

    return message

def post_processing(message:dict, attributes:dict[str,object]) -> dict:
    """
    Post-processing after all phases are complete.
    """
    write_meta(directory=attributes['directory'], attributes=attributes)

    if attributes["git_management"]:
        log_git_info = "**[Git Information]**\n\n"
        os.system("cd {}; git add .".format(attributes["directory"]))
        log_git_info += "cd {}; git add .\n".format(attributes["directory"])
        os.system("cd {}; git commit -m \"v{} Final Version\"".format(attributes["directory"], attributes["code_manager"].version))
        log_git_info += "cd {}; git commit -m \"v{} Final Version\"\n".format(attributes["directory"], attributes["code_manager"].version)
        log_visualize(log_git_info)

        git_info = "**[Git Log]**\n\n"
        import subprocess
        command = "cd {}; git log".format(attributes["directory"])
        completed_process = subprocess.run(command, shell=True, text=True, stdout=subprocess.PIPE)
        if completed_process.returncode == 0:
            log_output = completed_process.stdout
        else:
            log_output = "Error when executing " + command
        git_info += log_output
        log_visualize(git_info)

    post_info = "**[Post Info]**\n\n"
    now_time = now()
    time_format = "%Y%m%d%H%M%S"
    datetime1 = datetime.strptime(attributes["start_time"], time_format)
    datetime2 = datetime.strptime(now_time, time_format)
    duration = (datetime2 - datetime1).total_seconds()
    post_info += "Software Info: {}".format(
        get_info(attributes["directory"], attributes["log_filepath"]) + "\n\n🕑**duration**={:.2f}s\n\n".format(
            duration))
    post_info += "ChatDev Starts ({})".format(attributes["start_time"]) + "\n\n"
    post_info += "ChatDev Ends ({})".format(now_time) + "\n\n"

    directory = attributes['directory']
    if attributes["config"]["clear_structure"]:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isdir(file_path) and file_path.endswith("__pycache__"):
                shutil.rmtree(file_path, ignore_errors=True)
                post_info += "{} Removed.".format(file_path) + "\n\n"

    log_visualize(post_info)
    
    root = os.path.dirname(os.path.dirname(__file__))
    
    shutil.move(attributes["log_filepath"],
                os.path.join(root + "/assets/output/WareHouse", "_".join([attributes["project_name"], attributes["org_name"], attributes["start_time"]]),
                                os.path.basename(attributes["log_filepath"])))
    return message

def set_directory(directory,attributes):
    attributes['directory'] = directory
    attributes['code_manager'].directory = directory
    attributes["requirement_manager"].directory = directory
    attributes["manual_manager"].directory = directory
    
    if os.path.exists(directory) and len(os.listdir(directory)) > 0:
        new_directory = "{}.{}".format(directory, time.strftime("%Y%m%d%H%M%S", time.localtime()))
        shutil.copytree(directory, new_directory)

    if os.path.exists(directory):
        shutil.rmtree(directory)
        os.mkdir(directory)
    else:
        os.mkdir(directory)
        
def write_meta(directory, attributes:dict[str,object]) -> None:
        if not os.path.exists(directory):
            os.mkdir(directory)

        meta_filename = "meta.txt"
        with open(os.path.join(directory, meta_filename), "w", encoding="utf-8") as writer:
            writer.write("{}:\n{}\n\n".format("Task", attributes['task']))
            writer.write("{}:\n{}\n\n".format("Config", attributes['config']))
            writer.write("{}:\n{}\n\n".format("Modality", attributes['modality']))
            writer.write("{}:\n{}\n\n".format("Language", attributes['language']))
            writer.write("{}:\n{}\n\n".format("Code_Version", attributes['codes']))

def prompt_cost(model_type: str, num_prompt_tokens: float, num_completion_tokens: float):
    input_cost_map = {
        "gpt-3.5-turbo": 0.0005,
        "gpt-3.5-turbo-16k": 0.003,
        "gpt-3.5-turbo-0613": 0.0015,
        "gpt-3.5-turbo-16k-0613": 0.003,
        "gpt-4": 0.03,
        "gpt-4-0613": 0.03,
        "gpt-4-32k": 0.06,
        "gpt-4-turbo": 0.01,
        "gpt-4o": 0.005,
        "gpt-4o-mini": 0.00015,
    }

    output_cost_map = {
        "gpt-3.5-turbo": 0.0015,
        "gpt-3.5-turbo-16k": 0.004,
        "gpt-3.5-turbo-0613": 0.002,
        "gpt-3.5-turbo-16k-0613": 0.004,
        "gpt-4": 0.06,
        "gpt-4-0613": 0.06,
        "gpt-4-32k": 0.12,
        "gpt-4-turbo": 0.03,
        "gpt-4o": 0.015,
        "gpt-4o-mini": 0.0006,
    }

    if model_type not in input_cost_map or model_type not in output_cost_map:
        return -1

    return num_prompt_tokens * input_cost_map[model_type] / 1000.0 + num_completion_tokens * output_cost_map[model_type] / 1000.0

def get_info(dir, log_filepath):
    model_type = ""
    version_updates = -1
    num_code_files = -1
    num_png_files = -1
    num_doc_files = -1
    code_lines = -1
    env_lines = -1
    manual_lines = -1
    duration = -1
    num_utterance = -1
    num_reflection = -1
    num_prompt_tokens = -1
    num_completion_tokens = -1
    num_total_tokens = -1

    if os.path.exists(dir):
        filenames = os.listdir(dir)
        num_code_files = len([filename for filename in filenames if filename.endswith(".py")])
        num_png_files = len([filename for filename in filenames if filename.endswith(".png")])

        num_doc_files = 0
        for filename in filenames:
            if filename.endswith(".py") or filename.endswith(".png"):
                continue
            if os.path.isfile(os.path.join(dir, filename)):
                num_doc_files += 1

        if "requirements.txt" in filenames:
            lines = open(os.path.join(dir, "requirements.txt"), "r", encoding="utf8").read().split("\n")
            env_lines = len([line for line in lines if len(line.strip()) > 0])
        else:
            env_lines = -1

        if "manual.md" in filenames:
            lines = open(os.path.join(dir, "manual.md"), "r", encoding="utf8").read().split("\n")
            manual_lines = len([line for line in lines if len(line.strip()) > 0])
        else:
            manual_lines = -1

        code_lines = 0
        for filename in filenames:
            if filename.endswith(".py"):
                lines = open(os.path.join(dir, filename), "r", encoding="utf8").read().split("\n")
                code_lines += len([line for line in lines if len(line.strip()) > 0])

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        sublines = [line for line in lines if "| **model_type** |" in line]
        if len(sublines) > 0:
            model_type = sublines[0].split("| **model_type** | ModelType.")[-1].split(" | ")[0]
            model_type = model_type[:-2]
            if model_type == "GPT_3_5_TURBO" or model_type == "GPT_3_5_TURBO_NEW":
                model_type = "gpt-3.5-turbo"
            elif model_type == "GPT_4":
                model_type = "gpt-4"
            elif model_type == "GPT_4_32k":
                model_type = "gpt-4-32k"
            elif model_type == "GPT_4_TURBO":
                model_type = "gpt-4-turbo"
            elif model_type == "GPT_4O":
                model_type = "gpt-4o"
            elif model_type == "GPT_4O_MINI":
                model_type = "gpt-4o-mini"

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        start_lines = [line for line in lines if "**[Start Chat]**" in line]
        chat_lines = [line for line in lines if "<->" in line]
        num_utterance = len(start_lines) + len(chat_lines)

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        sublines = [line for line in lines if line.startswith("prompt_tokens:")]
        if len(sublines) > 0:
            nums = [int(line.split(": ")[-1]) for line in sublines]
            num_prompt_tokens = np.sum(nums)

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        sublines = [line for line in lines if line.startswith("completion_tokens:")]
        if len(sublines) > 0:
            nums = [int(line.split(": ")[-1]) for line in sublines]
            num_completion_tokens = np.sum(nums)
            
        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        sublines = [line for line in lines if line.startswith("total_tokens:")]
        if len(sublines) > 0:
            nums = [int(line.split(": ")[-1]) for line in sublines]
            num_total_tokens = np.sum(nums)

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")

        lines = open(log_filepath, "r", encoding="utf8").read().split("\n")
        num_reflection = 0
        for line in lines:
            if "on : Reflection" in line:
                num_reflection += 1

    cost = 0.0
    if num_png_files != -1:
        cost += num_png_files * 0.016
    if prompt_cost(model_type, num_prompt_tokens, num_completion_tokens) != -1:
        cost += prompt_cost(model_type, num_prompt_tokens, num_completion_tokens)

    # info = f"🕑duration={duration}s 💰cost=${cost} 🔨version_updates={version_updates} 📃num_code_files={num_code_files} 🏞num_png_files={num_png_files} 📚num_doc_files={num_doc_files} 📃code_lines={code_lines} 📋env_lines={env_lines} 📒manual_lines={manual_lines} 🗣num_utterances={num_utterance} 🤔num_self_reflections={num_reflection} ❓num_prompt_tokens={num_prompt_tokens} ❗num_completion_tokens={num_completion_tokens} ⁉️num_total_tokens={num_total_tokens}"

    info = "\n\n💰**cost**=${:.6f}\n\n🔨**version_updates**={}\n\n📃**num_code_files**={}\n\n🏞**num_png_files**={}\n\n📚**num_doc_files**={}\n\n📃**code_lines**={}\n\n📋**env_lines**={}\n\n📒**manual_lines**={}\n\n🗣**num_utterances**={}\n\n🤔**num_self_reflections**={}\n\n❓**num_prompt_tokens**={}\n\n❗**num_completion_tokens**={}\n\n🌟**num_total_tokens**={}" \
        .format(cost,
                version_updates,
                num_code_files,
                num_png_files,
                num_doc_files,
                code_lines,
                env_lines,
                manual_lines,
                num_utterance,
                num_reflection,
                num_prompt_tokens,
                num_completion_tokens,
                num_total_tokens)

    return info
