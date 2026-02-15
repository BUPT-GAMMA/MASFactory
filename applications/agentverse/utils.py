from masfactory import Agent, Node


def on_forward_before_hook(node: Node, input: dict) -> dict:
    return input


def on_forward_after_hook(node: Node, output: dict, input: dict) -> dict:
    print(f"================= {node.name} after forward =================")
    print(f"Attributes: {node.attributes}")
    if isinstance(node, Agent):
        print("---------------------------------------------------------------------------")
        print(f"Last system prompt: {node.last_prompt[0]}")
        print("---------------------------------------------------------------------------")
        print(f"Last user prompt: {node.last_prompt[1]}")
    print("-------------------------------------------------------------------------")
    print(f"Input: {input}")
    print("-------------------------------------------------------------------------")
    print(f"Output: {output}")
    print("========================================================================")

    return output
