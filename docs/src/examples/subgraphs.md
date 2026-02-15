# Subgraphs (`Graph`) and modular reuse

`Graph` is also a `Node`. This means you can package a group of nodes as a subgraph and embed it into a larger workflow.

This example splits “document processing” into two subgraphs:

- `document_preprocessing`: cleaning + validation
- `content_analysis`: extraction + summarization

## Message Passing View

- **Horizontal (Edge keys):** explicit field contracts between the main graph and subgraphs (e.g., `raw_document -> processed_document`)
- **Vertical (attributes):** can be used to share context across subgraphs; this example is horizontal-first

## Diagram
![Diagram](/imgs/examples/subgraph.png)

## Example code (Declarative + NodeTemplate)

```python
from masfactory import Agent, Graph, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

DocumentPreprocessing = NodeTemplate(
    Graph,
    nodes=[
        ("document_cleaner", BaseAgent(instructions="You clean documents and output the cleaned document.", prompt_template="{raw_document}")),
        ("format_validator", BaseAgent(instructions="You validate format and output the processed document and status.", prompt_template="{cleaned_document}")),
    ],
    edges=[
        ("entry", "document_cleaner", {"raw_document": "Raw document"}),
        ("document_cleaner", "format_validator", {"cleaned_document": "Cleaned document"}),
        ("format_validator", "exit", {"processed_document": "Processed document", "status": "Validation status"}),
    ],
)

ContentAnalysis = NodeTemplate(
    Graph,
    nodes=[
        ("info_extractor", BaseAgent(instructions="You extract key structured information.", prompt_template="{processed_document}\nStatus: {status}")),
        ("summarizer", BaseAgent(instructions="You produce a summary, key points, and a full analysis.", prompt_template="{extracted_info}")),
    ],
    edges=[
        ("entry", "info_extractor", {"processed_document": "Processed document", "status": "Validation status"}),
        ("info_extractor", "summarizer", {"extracted_info": "Extracted information"}),
        ("summarizer", "exit", {"summary": "Summary", "key_points": "Key points", "analysis_result": "Full analysis"}),
    ],
)

main = RootGraph(
    name="document_processing_workflow",
    nodes=[
        ("document_preprocessing", DocumentPreprocessing),
        ("content_analysis", ContentAnalysis),
    ],
    edges=[
        ("entry", "document_preprocessing", {"raw_document": "Raw document text"}),
        ("document_preprocessing", "content_analysis", {"processed_document": "Processed document", "status": "Validation status"}),
        ("content_analysis", "exit", {"summary": "Final summary", "key_points": "Key points", "analysis_result": "Analysis result"}),
    ],
)

main.build()
out, _attrs = main.invoke({"raw_document": "A short document to process..."})
print(out["summary"])
```

## Example code (Imperative, alternative)

```python
from masfactory import Agent, Graph, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

main = RootGraph(name="document_processing_workflow")

# --- Subgraph 1: preprocessing ---
pre = main.create_node(Graph, name="document_preprocessing")

document_cleaner = pre.create_node(
    Agent,
    name="document_cleaner",
    model=model,
    instructions="You clean documents and output the cleaned document.",
    prompt_template="{raw_document}",
)
format_validator = pre.create_node(
    Agent,
    name="format_validator",
    model=model,
    instructions="You validate format and output the processed document and status.",
    prompt_template="{cleaned_document}",
)

pre.edge_from_entry(document_cleaner, {"raw_document": "Raw document"})
pre.create_edge(document_cleaner, format_validator, {"cleaned_document": "Cleaned document"})
pre.edge_to_exit(
    format_validator,
    {"processed_document": "Processed document", "status": "Validation status"},
)

# --- Subgraph 2: analysis ---
ana = main.create_node(Graph, name="content_analysis")

info_extractor = ana.create_node(
    Agent,
    name="info_extractor",
    model=model,
    instructions="You extract key structured information.",
    prompt_template="{processed_document}\nStatus: {status}",
)
summarizer = ana.create_node(
    Agent,
    name="summarizer",
    model=model,
    instructions="You produce a summary, key points, and a full analysis.",
    prompt_template="{extracted_info}",
)

ana.edge_from_entry(info_extractor, {"processed_document": "Processed document", "status": "Validation status"})
ana.create_edge(info_extractor, summarizer, {"extracted_info": "Extracted information"})
ana.edge_to_exit(summarizer, {"summary": "Summary", "key_points": "Key points", "analysis_result": "Full analysis"})

# --- Wire subgraphs in main ---
main.edge_from_entry(pre, {"raw_document": "Raw document text"})
main.create_edge(pre, ana, {"processed_document": "Processed document", "status": "Validation status"})
main.edge_to_exit(ana, {"summary": "Final summary", "key_points": "Key points", "analysis_result": "Analysis result"})

main.build()
out, _attrs = main.invoke({"raw_document": "A short document to process..."})
print(out["summary"])
```

