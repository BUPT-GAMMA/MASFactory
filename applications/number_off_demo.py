from masfactory import RootGraph, OpenAIModel, LogicSwitch, Loop, SingleAgent, Agent
from masfactory import JsonMessageFormatter,Edge
import os
def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASEa_URL")
    graph = RootGraph("rootWorkflow")
    model = OpenAIModel(model_name="gpt-4o-mini", api_key=api_key, base_url=base_url)
    prompt = """
        Role
        You are a counting Agent in an automated workflow.

        Task
        Your sole task is to receive the count NUMBER from the previous Agent, add 1 to it, and then output the new number.

        Rules
        Your response must contain only your number.
        If NUMBER is empty or does not contain a valid number, it means you are the first to count, please output 1.
        Ignore any text in NUMBER other than the number.

    """
    def on_sending_hook(sender,receiver,message):
        print(f"sending: {sender.name} -> {receiver.name}: {message}")
  
    formatter = JsonMessageFormatter()
    loop:Loop = graph.create_node(Loop,"loop",max_iterations=3)
    agent_a:Agent = graph.create_node(Agent,"agent_a", prompt, formatter, model) 
    agent_b:Agent = graph.create_node(Agent,"agent_b", prompt, formatter, model)
    agent_c:Agent = graph.create_node(Agent,"agent_c", prompt, formatter, model)
    agent_d:Agent = graph.create_node(Agent,"agent_d", prompt, formatter, model) 
    agent_e:Agent = loop.create_node(Agent,"agent_e", prompt, formatter, model) 
    agent_f:Agent = loop.create_node(Agent,"agent_f", prompt, formatter, model)
    agent_g:Agent = loop.create_node(Agent,"agent_g", prompt, formatter, model)
    agent_h:Agent = graph.create_node(Agent,"agent_h", prompt, formatter, model)
    
    graph.edge_from_entry(agent_a,{"number":"your number"})
    graph.create_edge(agent_a,agent_b,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook) 
    graph.create_edge(agent_a,agent_c,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook)
    graph.create_edge(agent_b,agent_d,{"number1":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook) 
    graph.create_edge(agent_c,agent_d,{"number2":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook)
    loop.create_edge(agent_e,agent_f,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook)
    loop.create_edge(agent_f,agent_g,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook)
    loop.edge_from_controller(agent_e,{"number":"your number"}) 
    loop.edge_to_controller(agent_g,{"number":"your number"})
    graph.create_edge(agent_d,loop,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook)
    graph.create_edge(loop,agent_h,{"number":"your number"}).hooks.register(Edge.Hook.SEND_MESSAGE,on_sending_hook) 
    graph.edge_to_exit(agent_h,{"number":"your number"}) 
    
    graph.build()
    result = graph.invoke(input={"number":0})
    print(result)

if __name__ == "__main__":
    main()
    
   
    