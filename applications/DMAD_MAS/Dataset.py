from datasets import load_dataset
import os
import json

base_path = os.path.dirname(os.path.abspath(__file__))

def read_dataset(name, split=None):
    if name == "ScienceQA":
        data = load_dataset("derek-thomas/ScienceQA", split=split or "test")
    elif name == "mm-vet":
        meta_data = os.path.join(base_path, "dataset/mm-vet/mm-vet.json")
        with open(meta_data, "r", encoding="utf-8") as f:
            data = json.load(f)
    return data


def create_options(options):
    if options is not None:
        letters = ["(A) ", "(B) ", "(C) ", "(D) ", "(E) ", "(F) ", "(G) "]
        strs = "Options:\n"
        for i in range(len(options)):
            strs += letters[i]
            strs += options[i]
            strs += "\n"
        strs += "\n"
    else:
        strs = ""
    return strs


def create_prompt(question, options=None, context=None, lecture=None,
                  if_options=True, post=True):
    prompt = "Question:\n" + question + "\n\n"
    if if_options and options is not None:
        prompt += create_options(options)
    return prompt
