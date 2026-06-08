from masfactory import CustomNode, MessageBusGraph


def test_message_bus_collects_publishers_and_fans_out_to_subscribers():
    def publish_analysis(input_msg: dict[str, object]) -> dict[str, object]:
        return {"analysis": f"analysis:{input_msg['message']}"}

    def publish_risk(input_msg: dict[str, object]) -> dict[str, object]:
        return {"risk": f"risk:{input_msg['message']}"}

    def summarize(input_msg: dict[str, object]) -> dict[str, object]:
        return {
            "summary": "|".join(
                [
                    input_msg["analysis"],
                    input_msg["risk"],
                    str(len(input_msg["bus_messages"])),
                ]
            )
        }

    graph = MessageBusGraph(
        name="bus",
        publisher_configs=[
            {
                "node": {
                    "cls": CustomNode,
                    "name": "analysis_publisher",
                    "forward": publish_analysis,
                },
                "publish_keys": {"analysis": "analysis payload"},
            },
            {
                "node": {
                    "cls": CustomNode,
                    "name": "risk_publisher",
                    "forward": publish_risk,
                },
                "publish_keys": {"risk": "risk payload"},
            },
        ],
        subscriber_configs=[
            {
                "node": {
                    "cls": CustomNode,
                    "name": "summary_subscriber",
                    "forward": summarize,
                },
                "subscription_keys": {
                    "analysis": "analysis payload",
                    "risk": "risk payload",
                    "bus_messages": "bus history",
                },
                "output_keys": {"summary": "summary payload"},
            }
        ],
    )
    graph.build()

    output = graph._forward({"message": "task"})

    assert output == {"summary": "analysis:task|risk:task|1"}
    assert graph.attributes["bus_messages"] == [
        {"analysis": "analysis:task", "risk": "risk:task"}
    ]
    assert [node.name for node in graph.publishers] == [
        "analysis_publisher",
        "risk_publisher",
    ]
    assert [node.name for node in graph.subscribers] == ["summary_subscriber"]
