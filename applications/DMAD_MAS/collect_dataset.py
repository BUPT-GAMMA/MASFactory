from datasets import load_dataset
import argparse
import os

base_path = os.path.dirname(os.path.abspath(__file__))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="ScienceQA")
    args = parser.parse_args()
    
    path = os.path.join(base_path, "dataset", args.dataset)
    if not os.path.exists(path):
        os.makedirs(path)
    
    if args.dataset == "ScienceQA":
        dataset = load_dataset("derek-thomas/ScienceQA", split = "test")
        index = 0
        for data in dataset:
            image = data["image"]
            if image != None:
                image.save(os.path.join(path, f"{index}.png"))
                index += 1