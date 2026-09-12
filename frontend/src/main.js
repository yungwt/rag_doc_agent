import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/theme.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElIcons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
// 全局注册 Element Plus 图标，模板里直接 <el-icon><ChatDotRound/></el-icon> 用
for (const [name, comp] of Object.entries(ElIcons)) {
  app.component(name, comp)
}
app.use(router).use(ElementPlus, { locale: zhCn }).mount('#app')