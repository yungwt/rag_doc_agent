<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, parseError } from '../api'

const router = useRouter()
const mode = ref('login')
const loading = ref(false)
const form = reactive({ username: '', email: '', password: '' })

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'register') {
      await auth.register({ username: form.username, email: form.email || null, password: form.password })
      ElMessage.success('注册成功，请登录')
      mode.value = 'login'
      form.password = ''
    } else {
      await auth.login({ username: form.username, password: form.password })
      router.push('/chat')
    }
  } catch (e) {
    ElMessage.error(parseError(e))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="bg-deco" />
    <el-card class="login-card" shadow="hover" body-style="padding: 30px 28px 26px">
      <div class="title">
        <div class="logo-badge"><el-icon :size="26"><Reading /></el-icon></div>
        <h2>知识库助手</h2>
        <p class="subtitle">基于 RAG 的智能文档问答</p>
      </div>
      <el-tabs v-model="mode" class="tabs">
        <el-tab-pane label="登录" name="login" />
        <el-tab-pane label="注册" name="register" />
      </el-tabs>
      <el-form @submit.prevent="submit" label-position="top">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="'User'" size="large" />
        </el-form-item>
        <el-form-item v-if="mode === 'register'">
          <el-input v-model="form.email" placeholder="邮箱（可选）" :prefix-icon="'Message'" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="'Lock'" size="large" />
        </el-form-item>
        <el-button type="primary" :loading="loading" native-type="submit" size="large" style="width: 100%">
          {{ mode === 'login' ? '登 录' : '注 册' }}
        </el-button>
      </el-form>
      <p class="stack">FastAPI · LangChain · ChromaDB</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
  background: transparent;
}
/* 背景网格 + 光晕由 theme.css 的 body 提供，这里只叠一层同色渐隐，让登录页更聚焦 */
.bg-deco {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 20% 25%, rgba(34, 211, 238, 0.16), transparent 42%),
    radial-gradient(circle at 82% 75%, rgba(79, 140, 255, 0.18), transparent 45%),
    radial-gradient(circle at 50% 50%, transparent 30%, rgba(7, 11, 20, 0.55) 100%);
  pointer-events: none;
}
.login-card {
  position: relative;
  width: 400px;
  max-width: 100%;
  border-radius: 16px;
  overflow: hidden;
}
/* 卡片顶部一条渐变高光 */
.login-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: var(--grad);
  opacity: .9;
}
.title { text-align: center; margin-bottom: 20px; }
.logo-badge {
  width: 54px; height: 54px; margin: 0 auto 12px;
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, rgba(34, 211, 238, .18), rgba(79, 140, 255, .18));
  border: 1px solid rgba(34, 211, 238, .3);
  color: var(--accent-1);
  box-shadow: 0 0 26px rgba(34, 211, 238, .22), inset 0 0 18px rgba(34, 211, 238, .08);
}
.title h2 {
  margin: 0 0 5px;
  font-size: 22px;
  letter-spacing: .5px;
  background: var(--grad);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.subtitle { margin: 0; color: var(--text-2); font-size: 13px; letter-spacing: .4px; }
.tabs :deep(.el-tabs__item) { font-size: 15px; }
.tabs :deep(.el-tabs__nav-wrap::after) { background-color: var(--line); }
.stack {
  margin: 22px 0 0;
  text-align: center;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: .08em;
  color: var(--text-3);
}
</style>
