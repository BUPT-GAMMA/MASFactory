# 渐进式教程

`ChatDev` 是由`清华大学自然语言处理实验室（THUNLP）`与`面壁智能（OpenBMB）`联合发布的基于大语言模型的多智能体协作系统，它通过模拟虚拟软件公司的运营流程（需求分析、编码、测试等），利用智能体角色的沟通与协作来自动化完成软件开发全生命周期。

代码仓库：https://github.com/OpenBMB/ChatDev/tree/chatdev1.0

论文链接：https://arxiv.org/abs/2307.07924

本章将带领读者使用 MASFactory 的三种开发范式（声明式、命令式、VibeGraphing）从0开始复现`简化版的ChatDev`。
::: tip 注意
- THUNLP和OpenBMB 在2025年12月发布了更强大的ChatDev 2.0版本，不再局限于软件开发领域的标准工作流，而是能够低代码地构建任意多智能体工作流。本章我们复现的是简化版的1.0版本的ChatDev。
:::


推荐阅读顺序：

- 首次上手：先读 **声明式**，再对照 **命令式**。
- 对“从意图到多智能体系统”的开发方式感兴趣，直接阅读 **VibeGraph**。

入口：

- [声明式构建 ChatDev Lite](/zh/progressive/chatdev_declarative)
- [命令式构建 ChatDev Lite](/zh/progressive/chatdev_imperative)
- [使用VibeGraph 构建 ChatDev Lite](/zh/progressive/chatdev_vibegraph)

