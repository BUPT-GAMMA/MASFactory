# Progressive Tutorials

`ChatDev` is a multi-agent collaboration system released by THUNLP and OpenBMB. It simulates the operation of a virtual software company (requirements, coding, testing, etc.) and uses role-based agent communication to automate the software development lifecycle.

- Repo: https://github.com/OpenBMB/ChatDev/tree/chatdev1.0
- Paper: https://arxiv.org/abs/2307.07924

This chapter reproduces a simplified ChatDev (1.0-style) from scratch using MASFactory in three paradigms:

- **Declarative**: express structure with `nodes/edges` and reuse configuration via `NodeTemplate`
- **Imperative**: assemble the graph using `create_node / create_edge`
- **VibeGraph**: draft a `graph_design.json` from intent, then compile and run

::: tip Note
THUNLP and OpenBMB released a more capable ChatDev 2.0 in December 2025. It is no longer limited to standard software-development workflows and supports low-code construction of general multi-agent workflows. This chapter focuses on a simplified version of ChatDev 1.0.
:::

Suggested reading order:

- First time: start with **Declarative**, then compare **Imperative**
- Interested in “intent → structure”: go directly to **VibeGraph**

Entry points:

- [Declarative ChatDev Lite](/progressive/chatdev_declarative)
- [Imperative ChatDev Lite](/progressive/chatdev_imperative)
- [VibeGraph ChatDev Lite](/progressive/chatdev_vibegraph)
