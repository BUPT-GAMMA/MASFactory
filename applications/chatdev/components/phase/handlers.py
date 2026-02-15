import logging
import os
import re
import requests
import base64
import subprocess
import signal
import time
from applications.chatdev.chatdev.codes import Codes
from masfactory import Model

logger = logging.getLogger(__name__)

def codes_check_and_processing(rewrite_infos:str,format_field_key:str|list= None,codes_alias:str=None,allow_empty_codes:bool=False):
    def update_and_rewrite(messages:dict,attributes):
        nonlocal rewrite_infos,format_field_key,codes_alias
        generated_codes = attributes.get("codes","")
        if generated_codes == "" and allow_empty_codes:
            return messages
        code_manager:Codes = attributes.get("code_manager",Codes())

        code_manager._update_codes(generated_codes)
        if len(code_manager.codebooks.keys()) == 0:
            raise ValueError("No Valid Codes.")
        rewrite_infos_formatted = rewrite_infos
        if format_field_key:
            if isinstance(format_field_key,str):
                format_field_key = [format_field_key]
            format_fields_dict = {key:attributes[key] for key in format_field_key}
            rewrite_infos_formatted = rewrite_infos.format(format_fields_dict)
        code_manager._rewrite_codes(attributes.get("git_management",False),phase_info=rewrite_infos_formatted)
        attributes["code_manager"] = code_manager
        if codes_alias:
            attributes["codes_alias"] = attributes["codes"]
        attributes["codes"] = code_manager._get_codes()

        return messages
    return update_and_rewrite

def check_un_implemented_file(messages:dict, attributes:dict):
    unimplemented_file = ""  # Track unimplemented file
    for filename in (attributes.get('pyfiles') or []):  # Iterate over Python files
        code_content = open(os.path.join(attributes['directory'], filename)).read()  # Read file content
        lines = [line.strip() for line in code_content.split("\n") if line.strip() == "pass"]  # Find lines containing "pass"
        if len(lines) > 0 and attributes['num_tried'][filename] < attributes['max_num_implement']:  # If "pass" exists and max attempts not reached
            unimplemented_file = filename  # Mark as unimplemented file
            break
    attributes['num_tried'][unimplemented_file] += 1  # Increment attempt count
    attributes['unimplemented_file'] = unimplemented_file  # Update unimplemented file attribute
    return messages

def code_review_human_interaction(messages:dict, attributes:dict):
    provided_comments = []
    while True:
        user_input = input(">>>>>>")
        if user_input.strip().lower() == "end":
            break
        if user_input.strip().lower() == "exit":
            provided_comments = ["exit"]
            break
        provided_comments.append(user_input)
    messages["comments"] = '\n'.join(provided_comments)
    attributes["comments"] = '\n'.join(provided_comments)
    messages["skip_flag"] = messages["comments"].strip().lower() == "exit"
    return messages



def _generate_and_download_image(filename: str, description: str,directory:str,model:Model) -> None:


    # Check if file already exists
    if os.path.exists(os.path.join(directory, filename)):
        return

    # Clean description: remove .png suffix if present
    desc = description
    if desc.endswith(".png"):
        desc = desc.replace(".png", "")

    logger.info("%s: %s", filename, desc)
    try:
        # Use unified model adapter interface to generate image
        generated_images = model.generate_images(
            prompt=desc,
            n=1,
            size="256x256"
        )

        # Process response - could be URL or base64 data
        if generated_images and len(generated_images) > 0:
            img_data = generated_images[0]

            if "url" in img_data and img_data["url"]:
                img_url = img_data["url"]
                r = requests.get(img_url)
                filepath = os.path.join(directory, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                with open(filepath, "wb") as f:
                    f.write(r.content)
                    logger.info("%s Downloaded", filepath)
            elif "b64_json" in img_data and img_data["b64_json"]:
                # If base64 data provided, save directly
                filepath = os.path.join(directory, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(img_data["b64_json"]))
            else:
                pass
        else:
            pass
    except NotImplementedError as e:
        logger.warning("Image generation not implemented: %s", e)
        logger.info("Skipping image generation for %s", filename)
    except Exception as e:
        logger.warning("Error generating image for %s: %s", filename, e)




def generate_images_from_codes(messages:dict,attributes:dict):
    code_manager = attributes.get("code_manager", None)
    if not code_manager:
        # No code_manager, return directly without generating images
        return messages

    # Retrieve structured code list; _get_codes() should return list[dict] with "code" field
    codes_data = code_manager._get_codes()
    # Join all code fields into a single string for regex matching; compatible with different return types
    if isinstance(codes_data, list):
        joined_codes = "\n".join(
            (item.get("code", "") if isinstance(item, dict) else str(item))
            for item in codes_data
        )
    else:
        joined_codes = str(codes_data)

    # Use regex to find PNG image filenames in code (allow letters, digits, underscore, dash)
    regex = r"([\w\-\_]+\.png)"
    matches = re.finditer(regex, joined_codes, re.DOTALL)

    proposed_images = attributes.get("proposed_images", {}) or {}
    incorporated_images = attributes.get("incorporated_images", {}) or {}

    # Process each matched filename
    for match in matches:
        filename = match.group(1).strip()
        if not filename:
            continue
        # If filename in proposed images, use proposed description; otherwise derive from filename
        if filename in proposed_images:
            incorporated_images[filename] = proposed_images[filename]
        else:
            incorporated_images[filename] = filename.rsplit(".", 1)[0].replace("_", " ")

    attributes["incorporated_images"] = incorporated_images

    # Prepare actual image generation/download: require directory and image_model
    directory = attributes.get("directory", None)
    model = attributes.get("image_model", None)
    if not directory or not model:
        # Do not raise exception; log and return to avoid interrupting workflow
        logger.debug(
            "generate_images_from_codes: missing 'directory' or 'image_model' in attributes; skip image generation."
        )
        return messages

    # Generate actual image file for each incorporated image
    for filename, description in incorporated_images.items():
        try:
            _generate_and_download_image(filename, description, directory, model)
        except Exception as e:
            logger.warning("Failed to generate/download image %s: %s", filename, e)

    return messages

def get_proposed_images_from_message(messages:dict,attributes:dict):

    images = messages.get("images",[])
    if images == []:
        images = attributes.get("images",[])
    proposed_images = {}
    model = attributes.get("image_model", None)
    directory = attributes.get("directory",None)
    assert directory is not None, "directory must be provided"
    assert model is not None, "image_model must be provided"
    for image in images:
        filename = image["image_name"]
        description = image["description"]
        proposed_images[filename] = description
        _generate_and_download_image(filename, description,directory,model)
    attributes["proposed_images"] = proposed_images
    attributes["incorporated_images"] = proposed_images

    return messages


def _exist_bugs(messages:dict,attributes:dict) -> tuple[bool, str]:
    directory = attributes.get("directory",None)
    logger.debug("Enter exist bugs check")
    # Success message
    success_info = "The software run successfully without errors."
    try:
        # check if we are on windows or linux
        if os.name == 'nt':
            command = "cd {} && dir && python main.py".format(directory)
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            command = "cd {}; ls -l; python3 main.py;".format(directory)
            process = subprocess.Popen(command,
                                        shell=True,
                                        preexec_fn=os.setsid,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE
                                        )
        time.sleep(3)
        return_code = process.returncode
        # Check if the software is still running
        if process.poll() is None:
            if "killpg" in dir(os):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                os.kill(process.pid, signal.SIGTERM)
                if process.poll() is None:
                    os.kill(process.pid, signal.CTRL_BREAK_EVENT)

        if return_code == 0:
            return False, success_info
        else:
            error_output = process.stderr.read().decode('utf-8')
            if error_output:
                if "Traceback".lower() in error_output.lower():
                    errs = error_output.replace(directory + "/", "")
                    return True, errs
            else:
                return False, success_info
    except subprocess.CalledProcessError as e:
        return True, f"Error: {e}"
    except Exception as ex:
        return True, f"An error occurred: {ex}"

    return False, success_info
    
def fix_module_not_found_error(test_reports):
    # Check if test reports contain ModuleNotFoundError
    if "ModuleNotFoundError" in test_reports:
        # Use regex to find all missing module names
        for match in re.finditer(r"No module named '(\S+)'", test_reports, re.DOTALL):
            module = match.group(1)  # Extract module name
            # Install missing module using pip
            subprocess.Popen("uv pip install {}".format(module), shell=True).wait()
            # Log installation command
            # log_visualize("**[CMD Execute]**\n\n[CMD] uv pip install {}".format(module))

def check_bugs_and_get_error_summary(messages:dict, attributes:dict):
    messages = generate_images_from_codes(messages,attributes)
    (exist_bugs,test_reports) = _exist_bugs(messages, attributes)
    if "ModuleNotFoundError" in test_reports:
        fix_module_not_found_error(test_reports)
        pip_install_content = ""  # Initialize pip install content
        for match in re.finditer(r"No module named '(\S+)'", attributes['test_reports'], re.DOTALL):  # Find all missing modules
            module = match.group(1)  # Get module name
            pip_install_content += "{}\n```{}\n{}\n```\n".format("cmd", "bash", f"uv pip install {module}")  # Generate install command
            logger.info("Programmer resolve ModuleNotFoundError by:\n%s\n", pip_install_content)
        messages["error_summary"] = "nothing need to do"
        messages["skip_flag"] = True
    else:
        messages["exist_bugs_flag"] = exist_bugs
        messages["test_reports"] = test_reports
        messages["skip_flag"] = False
    return messages

def requirements_update_and_rewrite(messages:dict, attributes:dict):
    requirements_doc = attributes.get("requirement_manager",None)
    assert requirements_doc is not None, "requirements Document not provided in attributes"
    logger.debug("requirements_doc content is: %s", attributes.get("requirements", None))
    requirements_doc._update_docs(attributes.get("requirements",None), parse=False, predefined_filename="requirements.txt")
    requirements_doc._rewrite_docs()
    attributes["requirements"] = requirements_doc._get_docs()
    return messages

def manual_update_and_rewrite(messages:dict, attributes:dict):
    manuals_doc = attributes.get("manual_manager",None)
    assert manuals_doc is not None, "manuals Document not provided in attributes"
    manuals_doc._update_docs(attributes.get("manual", None), parse=False, predefined_filename="manual.md")
    manuals_doc._rewrite_docs()
    attributes["manual"] = manuals_doc._get_docs()
    return messages
