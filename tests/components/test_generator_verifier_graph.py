from masfactory import CustomNode, GeneratorVerifierGraph, NodeTemplate


def test_generator_verifier_retries_until_verifier_accepts():
    attempts = {"count": 0}

    def generate(input_msg: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        return {
            "message": {
                "draft": f"draft-{attempts['count']}",
                "attempt": attempts["count"],
                "source": input_msg["message"],
            }
        }

    def verify(input_msg: dict[str, object]) -> dict[str, object]:
        draft = input_msg["message"]
        accepted = draft["attempt"] >= 2
        return {
            "message": {
                "accepted": accepted,
                "final": draft["draft"] if accepted else None,
                "feedback": None if accepted else "revise",
            }
        }

    graph = GeneratorVerifierGraph(
        name="gv",
        generator=NodeTemplate(CustomNode, forward=generate),
        verifier=NodeTemplate(CustomNode, forward=verify),
        max_iterations=3,
    )
    graph.build()

    output = graph._forward({"message": {"task": "solve"}})

    assert attempts["count"] == 2
    assert output["message"]["accepted"] is True
    assert output["message"]["final"] == "draft-2"
    assert graph.generator.name == "gv_generator"
    assert graph.verifier.name == "gv_verifier"


def test_generator_verifier_evaluates_accept_condition_once_per_message():
    calls: list[dict[str, object]] = []

    def generate(_input_msg: dict[str, object]) -> dict[str, object]:
        return {"message": {"draft": "done"}}

    def verify(input_msg: dict[str, object]) -> dict[str, object]:
        return {"message": {**input_msg["message"], "accepted": True}}

    def accept_once(message: dict[str, object]) -> bool:
        calls.append(message)
        return True

    graph = GeneratorVerifierGraph(
        name="gv_once",
        generator=NodeTemplate(CustomNode, forward=generate),
        verifier=NodeTemplate(CustomNode, forward=verify),
        accept_condition_function=accept_once,
    )
    graph.build()

    output = graph._forward({"message": {"task": "solve"}})

    assert output["message"]["accepted"] is True
    assert len(calls) == 1
