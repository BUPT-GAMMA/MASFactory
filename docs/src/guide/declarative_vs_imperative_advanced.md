# Declarative vs. Imperative (Advanced)

This page covers the “engineering details” that are easy to miss in the quickstart comparison: when to choose which paradigm, how to keep graphs robust and maintainable, and how to make structures easier to preview and debug in Visualizer.

> For the entry-level side-by-side example, see: [Declarative vs. Imperative (Quickstart)](/start/declarative_vs_imperative)

---

## 1) Declarative vs. imperative

| Dimension | Declarative | Imperative |
| --- | --- | --- |
| Best for | Stable topology, readability | Topology assembled dynamically (config/runtime) |
| Code shape | “describe what the structure is” | “build the structure step by step” |
| Key difference | More direct and concise | More flexible; easier to parameterize and wrap as composites |
| Visualizer | Usually more stable previews | Complex control APIs may be harder to preview if over-customized |
| Flexibility | Medium (bounded by declarative expressiveness) | High (any Python logic) |

---

## 2) Declarative style

Declarative authoring is strong when:

1) **Structure is centralized**: topology changes are localized in `nodes/edges`.
2) **Assembly is stable**: node parameters are managed via `NodeTemplate`, avoiding maintenance risks of positional arguments.

For the full `NodeTemplate` mechanism (Shared/Factory scope, and `template_*` override rules), read:
[NodeTemplate (templates, scoping, and dependency lifecycles)](/guide/node_template).

---

## 3) Imperative style

Imperative authoring is strong when:

1) **Topology must be dynamic**: assemble by configuration or runtime decisions.
2) **Defaults can be centralized**: in imperative graphs, `NodeTemplate` is often used to centralize defaults like `model / formatters / memories / retrievers`, then override only a few fields per node.

---

## 4) Can I mix both?

Yes—and in practice, it is often the most maintainable approach.

- For complex subgraphs, build them imperatively, wrap them as a composite `Graph`, and then reference them declaratively in the parent graph.
- For small/static subgraphs, write them declaratively for readability and maintainability.

