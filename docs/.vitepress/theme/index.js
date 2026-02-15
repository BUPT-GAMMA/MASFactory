// .vitepress/theme/index.js
import DefaultTheme from 'vitepress/theme'
import ThemedDiagram from './components/ThemedDiagram.vue'
import './custom.css' // 引入你的自定义样式

export default {
  ...DefaultTheme,
  enhanceApp({ app }) {
    app.component('ThemedDiagram', ThemedDiagram)
  },
  // 你可以在这里进行其他主题扩展
  // Layout: () => { ... }
}
