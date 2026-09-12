import { createRouter, createWebHashHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import DocumentsView from './views/DocumentsView.vue'
import ChatView from './views/ChatView.vue'
import SettingsView from './views/SettingsView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/documents', component: DocumentsView },
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/settings', component: SettingsView },
  ],
})

export default router
