import os
import sys
import json
import argparse
from applications.chatdev_lite.chatdev.utils import now
from applications.chatdev_lite.chatdev.codes import Codes
from applications.chatdev_lite.chatdev.documents  import Documents
from masfactory import OpenAIModel
def get_config():
    # Get parent directory of current file folder
    root = os.path.dirname(os.path.dirname(__file__))
    sys.path.append(root)
    config_dir = os.path.join(root, "assets", "config")
    config_files = [
        "ChatChainConfig.json",
        "PhaseConfig.json",
        "RoleConfig.json"
    ]
    config_paths = []
    for config_file in config_files:
        company_config_path = os.path.join(config_dir, config_file)
        assert os.path.exists(company_config_path), f"{company_config_path} does not exist"
        config_paths.append(company_config_path)
    return tuple(config_paths)

config_path, config_phase_path, config_role_path = get_config()

def get_attributes(args:argparse.Namespace):
    env_keys = {
            "config": "Full configuration data loaded from the config file",
            "config_phase": "Phase configuration",
            "config_role": "Role configuration",
            "task": "the user input prompt for software",
            "project_name": "the user input name for software",
            "org_name": "the organization name of the human user",
            "model_name": "the model name for chat",
            "code_path": "The code path for any related project or repository",
            "start_time": "Start time of the session",
            "directory": "The project directory path",
            "log_filepath": "Path to the log file",
            "chatdev_prompt": "background prompt of chatdev",
            "seminar_conclusion": "conclusion of seminar",
            "chat_record": "the chat record",
            "current_iteration": "the current iteration",
            "git_management": "Flag indicating if git management is enabled",
            "modality": "The product modality determined from demand analysis",
            "description": "The task description",
            "ideas": "Creative ideas for the software",
            "language": "The programming language chosen for development",
            "gui": "GUI framework requirements",
            "code_manager": "The Object of Codes class",
            "codes": "The generated code snippets",
            "codes_alias": "the alias content for generated codes",
            "unimplemented_file": "the list of unimplemented files",
            "pyfiles": "the list of python files in the project",
            "num_tried": "the number of attempts for each file",
            "cycle_index": "the current cycle index",
            "images": "Incorporated image assets",
            "review_comments": "Code review comments and suggestions. If no comment, the value should be \"Finished\".",
            "modification_conclusion": "The conclusion of the review modification. e.g. Finished! or Still need to improve. ",
            "incorporated_images": "the list of incorporated images",
            "proposed_images": "the list of proposed images",
            "test_reports": "Test execution reports",
            "exist_bugs_flag": "Flag indicating if bugs exist",
            "error_summary": "",
            "modification_conclusion": "The conclusion of the review modification. e.g. Finished! or Still need to improve. ",
            "requirement_manager": "The Object of Documents class",
            "requirements": "The project dependency requirements",
            "manual_manager": "The Object of Documents class",
            "manual": "The user manual documentation",
            "discussion_finished": "True or False. True if the your discussion has reached a concreted conclusion, False otherwise. And if this flag is False.",
        }
    start_time = now()
    root = os.path.dirname(os.path.dirname(__file__))
    directory = os.path.join(root, "assets/output/WareHouse") 

    with open(config_path, 'r', encoding="utf8") as file:
        config = json.load(file)
    with open(config_phase_path, 'r', encoding="utf8") as file:
        config_phase = json.load(file)
    with open(config_role_path, 'r', encoding="utf8") as file:
        config_role = json.load(file)
        
    environments = {
        "config": config,
        "config_phase": config_phase,
        "config_role": config_role,
        "task": args.task,
        "project_name": args.name,
        "org_name": args.org,
        "model_name": args.model,
        "code_path": "",
        "start_time": start_time,
        "directory": None,
        "log_filepath": os.path.join(directory,
                                "{}.log".format("_".join([args.name, start_time]))),
        "chatdev_prompt": config['background_prompt'],
        "seminar_conclusion": "",
        "chat_record": "",
        "current_iteration": 0,
        "git_management": False,
        "modality": None,
        "description": None,
        "ideas": None,
        "language": None,
        "gui": "The software should be equipped with graphical user interface (GUI) so that user can visually and graphically use it; so you must choose a GUI framework (e.g., in Python, you can implement GUI via tkinter, Pygame, Flexx, PyGUI, etc,).",
        "code_manager": Codes(),
        "codes": None,
        "codes_alias": None,
        "unimplemented_file": None,
        "pyfiles": None,
        "num_tried": None,
        "cycle_index": None,
        "images": None,
        "review_comments": None,
        "modification_conclusion": None,
        "incorporated_images": None,
        "proposed_images": None,
        "test_reports": "",
        "exist_bugs_flag": None,
        "error_summary": None,
        "modification_conclusion": None,
        "requirement_manager": Documents(),
        "requirements": None,
        "manual_manager": Documents(),
        "manual": None,
        "discussion_finished": False,
        "image_model": OpenAIModel(model_name=args.model, api_key=args.api_key, base_url=args.base_url)
        }
    return env_keys, environments

