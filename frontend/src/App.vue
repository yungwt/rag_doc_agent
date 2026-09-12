<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, currentUser } from './api'

const route = useRoute()
const router = useRouter()
const user = computed(() => currentUser.get())

// 登录页不套外壳（否则顶栏会跟着出现，且卡片无法真正居中）
const isBare = computed(() => route.path === '/login')

const menu = [
  { path: '/chat', label: '对话', icon: 'ChatDotRound' },
  { path: '/documents', label: '文档管理', icon: 'Document' },
  { path: '/settings', label: '设置', icon: 'Setting' },
]

// 简单的登录态自检：没存用户就跳登录
onMounted(() => {
  if (!currentUser.get() && route.path !== '/login') router.replace('/login')
})

function onUserCommand(cmd) {
  if (cmd === 'logout') handleLogout()
}

async function handleLogout() {
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <!-- 裸页面（登录）：直接铺满视口 -->
  <router-view v-if="isBare" />

  <!-- 主布局：顶栏 + 主区 -->
  <div v-else class="layout">
    <header class="topbar">
      <div class="brand">
        <el-icon :size="22" class="brand-icon"><Reading /></el-icon>
        <span class="brand-title">知识库助手</span>
      </div>

      <nav class="nav">
        <router-link
          v-for="m in menu" :key="m.path" :to="m.path"
          class="nav-item" :class="{ active: route.path === m.path }"
        >
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </router-link>
      </nav>

      <div v-if="user" class="top-right">
        <el-dropdown trigger="click" @command="onUserCommand">
          <div class="user-chip">
            <el-avatar :size="30" class="avatar">{{ user.username?.[0]?.toUpperCase() || '?' }}</el-avatar>
            <span class="name">{{ user.username }}</span>
            <el-icon class="caret"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <span class="dd-email mono">{{ user.email || '未设置邮箱' }}</span>
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">
                <el-icon class="dd-danger"><SwitchButton /></el-icon>
                <span>退出登录</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <!-- 对话页保活：切走不销毁，生成中的加载态和已到达的回复都不会丢 -->
          <keep-alive :include="['ChatView']">
            <component :is="Component" />
          </keep-alive>
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style>
body { margin: 0; }
.layout {
  height: 100vh;
  height: 100dvh;
  display: flex; flex-direction: column;
  overflow: hidden;
}

/* ── 顶部导航条 ── */
.topbar {
  display: flex; align-items: center; gap: 28px;
  height: 56px; flex-shrink: 0;
  padding: 0 24px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(15, 22, 38, 0.92), rgba(9, 14, 24, 0.88));
  backdrop-filter: blur(12px);
}
.brand {
  display: flex; align-items: center; gap: 10px;
  font-size: 17px; font-weight: 600;
}
.brand-icon { color: var(--accent-1); }
.brand-title {
  background: var(--grad);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  letter-spacing: .5px;
}

.nav { display: flex; align-items: center; gap: 6px; flex: 1; }
.nav-item {
  display: flex; align-items: center; gap: 7px;
  height: 34px; padding: 0 16px;
  border-radius: 9px;
  color: var(--text-2); text-decoration: none;
  font-size: 14px;
  transition: all .15s;
}
.nav-item:hover { background: rgba(120, 160, 220, 0.08); color: var(--text-1); }
.nav-item.active {
  color: var(--text-1); font-weight: 600;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.2), rgba(79, 140, 255, 0.06));
  box-shadow: inset 0 -2px 0 var(--accent-1);
}
.nav-item.active .el-icon { color: var(--accent-1); }

.user-chip {
  display: flex; align-items: center; gap: 9px;
  padding: 5px 10px 5px 5px;
  border-radius: 999px;
  cursor: pointer;
  transition: background .15s;
}
.user-chip:hover { background: rgba(120, 160, 220, 0.08); }
.user-chip .avatar {
  background: linear-gradient(135deg, #22d3ee, #4f8cff);
  color: var(--on-accent); font-weight: 600; flex-shrink: 0;
}
.user-chip .name { font-size: 13.5px; font-weight: 600; color: var(--text-1); }
.user-chip .caret { font-size: 12px; color: var(--text-3); }
.dd-email { font-size: 12px; color: var(--text-3); }
.dd-danger { color: var(--el-color-danger); margin-right: 6px; }

/* ── 主区：flex 列，页面自己决定是铺满（对话）还是自然滚动（文档/设置） ── */
.main {
  flex: 1; min-height: 0;
  display: flex; flex-direction: column;
  min-width: 0;
  background: transparent;
  padding: 20px 24px;
  overflow-y: auto;
}
/* 页面根元素默认不被压缩，超出时由 .main 滚动；需要铺满的页面在自身样式里声明 flex:1 */
.main > * { flex-shrink: 0; }
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
