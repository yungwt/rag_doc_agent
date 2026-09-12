import axios from 'axios'

// 同源代理转发到 FastAPI，Cookie 自动携带
const http = axios.create({ baseURL: '/api', timeout: 120000 })

// FastAPI / Starlette 自带的英文兜底文案，遇到这些才换用更友好的中文
const FRAMEWORK_TEXT = new Set(['Not Found', 'Method Not Allowed', 'Internal Server Error'])

/**
 * 把后端响应里的 detail / 网络错误统一解析成人类可读字符串。
 * 规则：后端给了可读文案就用后端的（后端所有业务错误都是中文提示），
 * 只有后端没给（框架默认英文、纯 500、网络断开）时才用下面的中文兜底。
 * - 401：只给可读文案，跳登录页交给响应拦截器在续期失败后处理
 * - 422：Pydantic 校验，把 detail 数组逐条拼成 "字段 X：msg"
 * - 网络断开：固定文案
 */
export function parseError(err) {
  if (!err.response) return '无法连接到服务器，请检查后端是否在运行'
  const { status, data } = err.response
  const detail = data?.detail

  // 401：文案优先用后端的（"账号已被禁用""未登录"等）。
  // 这里不自己跳登录页——拦截器会先尝试续期，只有续期失败才跳，
  // 否则会出现"刚续期成功却被踢走"的竞态。
  if (status === 401) {
    return typeof detail === 'string' && detail ? detail : '登录已过期，请重新登录'
  }

  // 422：Pydantic 校验，detail 是数组，逐条拼成 "字段 X：msg"
  if (status === 422 && Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc || []).slice(1).join('.') || '字段'}：${d.msg}`)
      .join('；')
  }

  // 后端给了可读文案就直接用
  if (typeof detail === 'string' && detail && !FRAMEWORK_TEXT.has(detail)) return detail

  // 只有后端没给的时候才用中文兜底
  if (status === 403) return '没有权限'
  if (status === 404) return '资源不存在'
  if (status === 503) return '服务暂时不可用，请稍后重试'
  if (status >= 500) return '服务器内部错误'
  return `请求失败（${status}）`
}

// 当前用户信息（登录成功后存进 localStorage，给 App.vue / 侧边栏用）
const USER_KEY = 'rag_user'
export const currentUser = {
  get: () => {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
  },
  set: (u) => localStorage.setItem(USER_KEY, JSON.stringify(u)),
  clear: () => localStorage.removeItem(USER_KEY),
}

/**
 * access_token 只活 30 分钟，过期后业务接口返回 401。这里自动调
 * /auth/refresh 换新令牌再重放原请求，用户无感；刷新失败才回登录页。
 *
 * refreshing 是"单飞"标记：并发 401 共用同一次刷新。后端刷新会轮换令牌，
 * 同时发多次会让后到的请求拿着已作废的旧令牌失败，反而把用户挤下线。
 */
let refreshing = null

http.interceptors.response.use(
  (res) => res,
  async (err) => {
    const config = err.config
    // 认证接口自身的 401（含 /auth/refresh）不续期，避免无限递归
    const isAuthCall = /^\/auth\//.test(config?.url || '')

    if (err.response?.status === 401 && !isAuthCall && config && !config._retried) {
      try {
        refreshing = refreshing || http.post('/auth/refresh').finally(() => { refreshing = null })
        await refreshing
      } catch {
        // 刷新也失败 → 确实登不上了，清干净并回登录页
        currentUser.clear()
        if (location.hash !== '#/login') location.hash = '#/login'
        return Promise.reject(err)
      }
      config._retried = true  // 标记已重放过，防止新令牌仍 401 时无限循环
      return http(config)
    }
    return Promise.reject(err)
  }
)

export const auth = {
  register: (data) => http.post('/auth/register', data),
  login: async (data) => {
    const res = await http.post('/auth/login', data)
    currentUser.set(res.data)
    return res
  },
  logout: async () => {
    try { await http.post('/auth/logout') } finally { currentUser.clear() }
  },
}

export const documents = {
  list: (skip = 0, limit = 20, status = 'all') => http.get('/documents/', { params: { skip, limit, status } }),
  upload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/documents/upload', form)
  },
  remove: (id) => http.delete(`/documents/${id}`),
}

export const sessions = {
  list: (skip = 0, limit = 50) => http.get('/sessions/', { params: { skip, limit } }),
  create: (title = '新对话') => http.post('/sessions/', { title }),
  remove: (id) => http.delete(`/sessions/${id}`),
  messages: (id, limit = 100) => http.get(`/sessions/${id}/messages`, { params: { limit } }),
}

export const qa = {
  ask: (question, sessionId) => http.post('/qa/', { question, session_id: sessionId }),
}

export const settingsApi = {
  get: () => http.get('/settings/'),
  updateHistoryLimit: (historyLimit) => http.put('/settings/history-limit', { history_limit: historyLimit }),
}