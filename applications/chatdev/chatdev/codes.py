import difflib
import os
import re
import subprocess
from applications.chatdev.chatdev.utils import log_visualize


class Codes:
    """
    Manages code files, including extraction, updates, rewriting, and version control.
    """

    def __init__(self, generated_content: list | dict | None = None):
        """
        Initializes the Codes class and stores parsed generated code content in codebooks.
        Args:
            generated_content: Generated code content (in string format).
        """
        self.directory: str = None  # Project directory path
        self.version: float = 0.0  # Code version
        self.generated_content: str = generated_content  # Generated code content
        self.codebooks = {}  # Stores filename and code content pairs
        
        def extract_filename_from_code(code):
            """
            Extracts filename from code content.
            Args:
                code: Code content
            Returns:
                file_name: Extracted filename
            """
            file_name = ""
            regex_extract = r"class (\S+?):\n"
            matches_extract = re.finditer(regex_extract, code, re.DOTALL)
            for match_extract in matches_extract:
                file_name = match_extract.group(1)
            file_name = file_name.lower().split("(")[0] + ".py"
            return file_name

        def process_code_item(item_dict):
            """
            Processes a single code dictionary item, extracting filename and code, and storing them in codebooks.
            Args:
                item_dict: Dictionary containing filename and code
            """
            filename = item_dict.get("filename", "").lower()
            code = item_dict.get("code", "")
            # If code contains __main__, set filename as main.py
            if "__main__" in code:
                filename = "main.py"
            # If filename is not provided, try extracting it from code
            if filename == "":
                filename = extract_filename_from_code(code)
            assert filename != "", "Filename extraction failed"
            if filename and code:
                self.codebooks[filename] = self._format_code(code)

        # Parse and store the generated code if content is provided
        if generated_content:
            if isinstance(generated_content, list):
                for item in generated_content:
                    process_code_item(item)
            elif isinstance(generated_content, dict):
                process_code_item(generated_content)

    def _format_code(self, code):
        """
        Formats code by removing empty lines.
        Args:
            code: Raw code content
        Returns:
            formatted code
        """
        return "\n".join([line for line in code.split("\n") if len(line.strip()) > 0])

    def _update_codes(self, generated_content):
        """
        Updates code content, compares old and new, and logs the changes.
        Args:
            generated_content: New generated code content
        """
        new_codes = Codes(generated_content)
        differ = difflib.Differ()
        for key in new_codes.codebooks.keys():
            if key not in self.codebooks.keys() or self.codebooks[key] != new_codes.codebooks[key]:
                update_codes_content = "**[Update Codes]**\n\n"
                update_codes_content += "{} updated.\n".format(key)
                old_codes_content = self.codebooks.get(key, "# None")
                new_codes_content = new_codes.codebooks[key]

                lines_old = old_codes_content.splitlines()
                lines_new = new_codes_content.splitlines()

                unified_diff = difflib.unified_diff(lines_old, lines_new, lineterm='', fromfile='Old', tofile='New')
                unified_diff = '\n'.join(unified_diff)
                update_codes_content += "\n\n" + """```
'''
'''\n""" + unified_diff + "\n```"

                log_visualize(update_codes_content)
                self.codebooks[key] = new_codes.codebooks[key]

    def _rewrite_codes(self, git_management, phase_info=None) -> None:
        """
        Rewrites code files to disk, with optional Git management.
        Args:
            git_management: Whether to enable Git management
            phase_info: Current phase information (for Git commit message)
        """
        directory = self.directory
        rewrite_codes_content = "**[Rewrite Codes]**\n\n"
        
        if os.path.exists(directory) and len(os.listdir(directory)) > 0:
            self.version += 1.0
        if not os.path.exists(directory):
            os.mkdir(self.directory)
            rewrite_codes_content += "{} Created\n".format(directory)

        for filename in self.codebooks.keys():
            filepath = os.path.join(directory, filename)
            with open(filepath, "w", encoding="utf-8") as writer:
                writer.write(self.codebooks[filename])
                rewrite_codes_content += os.path.join(directory, filename) + " Wrote\n"

        if git_management:
            if not phase_info:
                phase_info = ""
            log_git_info = "**[Git Information]**\n\n"
            if self.version == 1.0:
                os.system(f"cd {self.directory}; git init")
                log_git_info += f"cd {self.directory}; git init\n"
            os.system(f"cd {self.directory}; git add .")
            log_git_info += f"cd {self.directory}; git add .\n"

            completed_process = subprocess.run(f"cd {self.directory}; git status", shell=True, text=True, stdout=subprocess.PIPE)
            if "nothing to commit" in completed_process.stdout:
                self.version -= 1.0
                return

            os.system(f"cd {self.directory}; git commit -m 'v{self.version} {phase_info}'")
            log_git_info += f"cd {self.directory}; git commit -m 'v{self.version} {phase_info}'\n"
            if self.version == 1.0:
                os.system(f"cd {os.path.dirname(os.path.dirname(self.directory))}; git submodule add ./{os.path.basename(self.directory)} WareHouse/{os.path.basename(self.directory)}")
                log_git_info += f"cd {os.path.dirname(os.path.dirname(self.directory))}; git submodule add ./{os.path.basename(self.directory)} WareHouse/{os.path.basename(self.directory)}\n"
            log_visualize(rewrite_codes_content)
            log_visualize(log_git_info)

    def _get_codes(self) -> list:
        """
        Retrieves all code content in a structured list format.
        Returns:
            List of code file information, each item is a dictionary with filename, language, docstring, and code
        """
        codes_list = []
        for filename in self.codebooks.keys():
            language = "python" if filename.endswith(".py") else filename.split(".")[-1]
            code_content = self.codebooks[filename]
            docstring = ""
            if language == "python":
                docstring_match = re.search(r'^\s*["\'"]{3}(.*?)["\'"]{3}', code_content, re.DOTALL | re.MULTILINE)
                if docstring_match:
                    docstring = docstring_match.group(1).strip()

            codes_list.append({
                "filename": filename,
                "language": language,
                "docstring": docstring,
                "code": code_content
            })

        return codes_list

    def _load_from_hardware(self, directory) -> None:
        """
        Loads code files from disk into codebooks.
        Args:
            directory: Directory containing code files
        """
        assert len([filename for filename in os.listdir(directory) if filename.endswith(".py")]) > 0
        for root, directories, filenames in os.walk(directory):
            for filename in filenames:
                if filename.endswith(".py"):
                    code = open(os.path.join(directory, filename), "r", encoding="utf-8").read()
                    self.codebooks[filename] = self._format_code(code)
        log_visualize(f"{len(self.codebooks.keys())} files read from {directory}")
