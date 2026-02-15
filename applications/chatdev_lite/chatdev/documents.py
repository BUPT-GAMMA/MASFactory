import re
import os
import time
from colorama import Fore


class Documents:
    """
    Manages document content, including parsing, updating, rewriting, and retrieving document content.
    """

    def __init__(self, generated_content="", parse=True, predefined_filename=None):
        """
        Initializes the Documents class, parsing the generated document content and storing it in docbooks.
        Args:
            generated_content: Generated document content (string format)
            parse: Whether to parse document content (default is True)
            predefined_filename: Predefined filename (used if not parsing)
        """
        self.directory: str = None  # Directory to store documents
        self.generated_content = generated_content  # Generated document content
        self.docbooks = {}  # Stores filenames and their corresponding document content

        # Parse and store the document content if it's not empty
        if generated_content != "":
            if parse:
                # Use regex to extract document content
                regex = r"```\n(.*?)```"
                matches = re.finditer(regex, self.generated_content, re.DOTALL)
                for match in matches:
                    filename = "requirements.txt"  # Default filename
                    doc = match.group(1)  # Extract document content
                    self.docbooks[filename] = doc
            else:
                # If not parsing, use the predefined filename and content
                self.docbooks[predefined_filename] = self.generated_content

    def _update_docs(self, generated_content, parse=True, predefined_filename=""):
        """
        Updates document content, compares old and new content, and prints update information.
        Args:
            generated_content: New generated document content
            parse: Whether to parse the content (default is True)
            predefined_filename: Predefined filename (used if not parsing)
        """
        new_docs = Documents(generated_content, parse, predefined_filename)  # Create a new Documents instance
        for key in new_docs.docbooks.keys():
            # If the document content has changed or is new, update docbooks
            if key not in self.docbooks.keys() or self.docbooks[key] != new_docs.docbooks[key]:
                print(f"{key} updated.")  # Print updated filename
                print(Fore.WHITE + f"------Old:\n{self.docbooks.get(key, '# None')}\n------New:\n{new_docs.docbooks[key]}")
                self.docbooks[key] = new_docs.docbooks[key]  # Update docbooks

    def _rewrite_docs(self):
        """
        Writes document content to disk.
        """
        directory = self.directory  # Get the document storage directory
        if not os.path.exists(directory):
            # Create the directory if it doesn't exist
            os.mkdir(directory)
            print(f"{directory} Created.")
        for filename in self.docbooks.keys():
            # Write document content to corresponding files
            with open(os.path.join(directory, filename), "w", encoding="utf-8") as writer:
                writer.write(self.docbooks[filename])
                print(f"{os.path.join(directory, filename)} Written")

    def _get_docs(self):
        """
        Retrieves all document content, formatted as a string with filenames and content.
        Returns:
            Formatted document content string
        """
        content = ""
        for filename in self.docbooks.keys():
            # Concatenate filename and content
            content += f"{filename}\n```\n{self.docbooks[filename]}\n```\n\n"
        return content
