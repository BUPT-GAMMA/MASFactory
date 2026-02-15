import os
import re
import requests
import base64
import subprocess
import signal
import time
from applications.chatdev_lite.chatdev.codes import Codes
from masfactory import Model

def _generate_and_download_image(filename: str, description: str,directory:str,model:Model) -> None:
    # Check if file already exists
    if os.path.exists(os.path.join(directory, filename)):
        return

    # Clean description: remove .png suffix if present
    desc = description
    if desc.endswith(".png"):
        desc = desc.replace(".png", "")

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
                # If URL provided, download the image
                # download(img_data["url"], filename)
                # Download
                img_url = img_data["url"]
                r = requests.get(img_url)
                filepath = os.path.join(directory, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                with open(filepath, "wb") as f:
                    f.write(r.content)
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
        pass
    except Exception as e:
        pass




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
        return messages

    # Generate actual image file for each incorporated image
    for filename, description in incorporated_images.items():
        try:
            _generate_and_download_image(filename, description, directory, model)
        except Exception as e:
            pass

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
