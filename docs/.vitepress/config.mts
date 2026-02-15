import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "MASFactory",
  description: "Documentation for MASFactory",
  base: "/MASFactory/",
  srcDir: 'src',

  themeConfig: {
    logo: {
      light: '/svg/mark.svg',
      dark: '/svg/mark-dark.svg',
      alt: 'MASFactory'
    },
    siteTitle: '<span class="mf-site-title"><span class="mf-mas">MAS</span><span class="mf-factory">Factory</span></span>',

    nav: [
      { text: 'Quick Start', link: '/start/introduction' },
      { text: 'Progressive Tutorials', link: '/progressive/' },
      { text: 'API Documentation', link: '/api_reference' },
    ],

    sidebar: [
      {
        text: 'Quick Start',
        items: [
          { text: 'MASFactory Introduction', link: '/start/introduction' },
          { text: 'Installation', link: '/start/installation' },
          { text: 'First Code', link: '/start/the_first_code' },
          { text: 'VibeGraphing', link: '/start/vibegraphing' },
          { text: 'Declarative vs Imperative', link: '/start/declarative_vs_imperative' },
          { text: 'MASFactory Visualizer', link: '/start/visualizer' }
        ]
      },
      {
        text: 'Progressive Tutorials',
        items: [
          { text: 'Overview', link: '/progressive/' },
          { text: 'Declarative ChatDev Lite', link: '/progressive/chatdev_declarative' },
          { text: 'Imperative ChatDev Lite', link: '/progressive/chatdev_imperative' },
          { text: 'VibeGraph ChatDev Lite', link: '/progressive/chatdev_vibegraph' },
        ]
      },
      {
        text: "Development Guide",
        items: [
          { text: 'Core Concepts', link: '/guide/concepts' },
          { text: 'Model Adapters', link: '/guide/model_adapter' },
          { text: 'Message Passing', link: '/guide/message_passing' },
          { text: 'Declarative vs Imperative', link: '/guide/declarative_vs_imperative_advanced' },
          { text: 'Basic Components', link: '/guide/components' },
          { text: 'Agent Runtime', link: '/guide/agent_runtime' },
          { text: 'NodeTemplate', link: '/guide/node_template' },
          { text: 'Composite Components', link: '/guide/composite_components' },
          { text: 'VibeGraphing', link: '/guide/vibegraphing' },
          { text: 'Context Adapters', link: '/guide/context_adapters' },
          { text: 'Tool Calling', link: '/guide/tools' },
          { text: 'MASFactory Visualizer', link: '/guide/visualizer' },
          { text: 'Runtime Hooks', link: '/guide/runtime_hooks' },
        ]
      },
      {
        text: "Examples",
        items: [
          { text: "Sequential Workflow", link: '/examples/sequential_workflow' },
          { text: "Parallel Branching", link: '/examples/parallel_branching' },
          { text: "Conditional Branching", link: '/examples/conditional_branching' },
          { text: "Subgraphs", link: '/examples/subgraphs' },
          { text: "Looping", link: '/examples/looping' },
          { text: "Custom Node", link: '/examples/custom_node' },
          { text: "Agents", link: '/examples/agents' },
          { text: "Node Attributes", link: '/examples/attributes' },
          { text: "VibeGraphing", link: '/examples/vibegraphing' },
          { text: "Interface Extensions", link: '/examples/extensions' }
        ]
      },
      {
        text: "API Documentation",
        link: "/api_reference"
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/BUPT-GAMMA/MASFactory' }
    ]
  },

  locales: {
    root: {
      label: "English",
      lang: "en"
    },
    zh: {
      label: "简体中文",
      lang: "zh",
      link: '/zh/',
      themeConfig: {
        nav: [
          { text: '快速入门', link: '/zh/start/introduction' },
          { text: '渐进式教程', link: '/zh/progressive/' },
          { text: 'API 文档', link: '/zh/api_reference' },
        ],
        sidebar: [
          {
            text: '快速入门',
            items: [
              { text: 'MASFactory 简介', link: '/zh/start/introduction' },
              { text: '安装', link: '/zh/start/installation' },
              { text: '第一行代码', link: '/zh/start/the_first_code' },
              { text: 'VibeGraphing 入门', link: '/zh/start/vibegraphing' },
              { text: '声明式 vs 命令式', link: '/zh/start/declarative_vs_imperative' },
              { text: 'MASFactory Visualizer', link: '/zh/start/visualizer' },
            ]
          },
          {
            text: '渐进式教程',
            items: [
              { text: '概览', link: '/zh/progressive/' },
              { text: '声明式构建 ChatDev Lite', link: '/zh/progressive/chatdev_declarative' },
              { text: '命令式构建 ChatDev Lite', link: '/zh/progressive/chatdev_imperative' },
              { text: 'VibeGraph 构建 ChatDev Lite', link: '/zh/progressive/chatdev_vibegraph' },
            ]
          },
          {
            text: "开发指南",
            items: [
              { text: '核心概念', link: '/zh/guide/concepts' },
              { text: '消息传递', link: '/zh/guide/message_passing' },
              { text: '命令式 vs 声明式（进阶）', link: '/zh/guide/declarative_vs_imperative_advanced' },
              { text: '模型适配器', link: '/zh/guide/model_adapter' },
              { text: '基础组件', link: '/zh/guide/components' },
              { text: 'Agent 运行机制', link: '/zh/guide/agent_runtime' },
              { text: 'NodeTemplate', link: '/zh/guide/node_template' },
              { text: '复合组件', link: '/zh/guide/composite_components' },
              { text: 'VibeGraphing', link: '/zh/guide/vibegraphing' },
              { text: 'Memory/RAG/MCP', link: '/zh/guide/context_adapters' },
              { text: '工具调用', link: '/zh/guide/tools' },
              { text: 'MASFactory Visualizer', link: '/zh/guide/visualizer' },
              { text: '运行时 Hooks', link: '/zh/guide/runtime_hooks' },
            ]
          },
          {
            text: "示例",
            items: [
              { text: "串行工作流", link: '/zh/examples/sequential_workflow' },
              { text: "并行分支", link: '/zh/examples/parallel_branching' },
              { text: "条件分支", link: '/zh/examples/conditional_branching' },
              { text: "子图", link: '/zh/examples/subgraphs' },
              { text: "循环", link: '/zh/examples/looping' },
              { text: "自定义节点", link: '/zh/examples/custom_node' },
              { text: "Agents", link: '/zh/examples/agents' },
              { text: "节点变量", link: '/zh/examples/attributes' },
              { text: "VibeGraphing", link: '/zh/examples/vibegraphing' },
              { text: "接口扩展", link: '/zh/examples/extensions' }
            ]
          },
          {
            text: "API 文档",
            link: "/zh/api_reference"
          }
        ]
      }
    }
  }
})