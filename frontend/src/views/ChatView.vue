<script setup>
import { computed, nextTick, onActivated, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { qa, sessions, parseError } from '../api'
import { fmtAgo, fmtClock } from '../utils/format'

// 供 <keep-alive include="ChatView"> 匹配（切走不销毁，生成中的状态得以保留）
defineOptions({ name: 'ChatView' })

const LAST_SESSION_KEY = 'rag_last_session'
const router = useRouter()
const sessionList = ref([])
const currentSessionId = ref(null)
const messages = ref([])
const messagesTotal = ref(0)   // 后端返回的会话消息总数（可能大于已加载数）
const question = ref('')
const asking = ref(false)
const searchKey = ref('')
const listRef = ref(null)
const inputRef = ref(null)

const INITIAL_LIMIT = 100      // 首次只拉最近 100 条，更早的按需全量加载

// 截断时在消息区顶部显示"加载更多"；本地新提问会增加 messages.length，
// total - length 恰好等于还没加载出来的更早消息数
const hasMore = computed(() => messagesTotal.value > messages.value.length)
const hiddenCount = computed(() => Math.max(messagesTotal.value - messages.value.length, 0))
const msgCount = computed(() => Math.max(messagesTotal.value, messages.value.length))

const filteredSessions = computed(() => {
  const k = searchKey.value.trim().toLowerCase()
  return k ? sessionList.value.filter((s) => s.title.toLowerCase().includes(k)) : sessionList.value
})

const currentTitle = computed(
  () => sessionList.value.find((s) => s.id === currentSessionId.value)?.title || '对话',
)
const sourceCount = computed(
  () => messages.value.reduce((n, m) => n + (m.sources?.length || 0), 0),
)
// 来源徽章用：按 document_id 去重，数出涉及几篇文档
const srcDocCount = (list) => new Set(list.map((s) => s.document_id)).size

async function loadSessions() {
  try {
    const { data } = await sessions.list()
    sessionList.value = data.sessions
  } catch (e) { ElMessage.error(parseError(e)) }
}

async function selectSession(s) {
  currentSessionId.value = s.id
  try {
    const { data } = await sessions.messages(s.id, INITIAL_LIMIT)
    messages.value = data.messages
    messagesTotal.value = data.total
    scrollToBottom()
  } catch (e) { ElMessage.error(parseError(e)) }
}

// 全量加载更早的消息（后端 limit 上限 1000，单会话超过此数的情况基本不存在）
async function loadAllMessages() {
  try {
    const wrap = listRef.value?.$el?.querySelector('.el-scrollbar__wrap')
    const prevHeight = wrap?.scrollHeight || 0
    const { data } = await sessions.messages(currentSessionId.value, 1000)
    messages.value = data.messages
    messagesTotal.value = data.total
    // 前插了 N 条更早消息，把视口锚定在原来看到的位置上，避免画面跳动
    nextTick(() => {
      const w = listRef.value?.$el?.querySelector('.el-scrollbar__wrap')
      if (w) w.scrollTop = w.scrollHeight - prevHeight
    })
  } catch (e) { ElMessage.error(parseError(e)) }
}

async function newSession() {
  try {
    const { data } = await sessions.create()
    await loadSessions()
    currentSessionId.value = data.id
    messages.value = []
    focusInput()
  } catch (e) { ElMessage.error(parseError(e)) }
}

async function removeSession(s) {
  try {
    await ElMessageBox.confirm(`确定删除会话「${s.title}」？消息会一并清除`, '删除会话', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await sessions.remove(s.id)
    if (currentSessionId.value === s.id) { currentSessionId.value = null; messages.value = []; messagesTotal.value = 0 }
    ElMessage.success('已删除')
    loadSessions()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(parseError(e))
  }
}

async function ask() {
  const text = question.value.trim()
  if (!text) return
  if (!currentSessionId.value) await newSession()

  messages.value.push({ role: 'user', content: text, creat_time: new Date().toISOString() })
  question.value = ''
  await askAndAppend(text)
}

async function askAndAppend(text) {
  asking.value = true
  scrollToBottom()
  try {
    const { data } = await qa.ask(text, currentSessionId.value)
    messages.value.push({
      role: 'assistant', content: data.answer, sources: data.sources,
      creat_time: new Date().toISOString(),
    })
  } catch (e) {
    ElMessage.error(parseError(e))
  } finally {
    asking.value = false
    scrollToBottom()
    focusInput()
  }
}

async function copyAnswer(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch { ElMessage.warning('复制失败，请手动选择') }
}

function focusInput() { nextTick(() => inputRef.value?.focus()) }

function scrollToBottom() {
  nextTick(() => {
    const sb = listRef.value
    if (!sb) return
    // el-scrollbar 真正的滚动容器是内层 __wrap，直接改根元素 scrollTop 是无效的
    const wrap = sb.$el?.querySelector('.el-scrollbar__wrap')
    if (wrap) sb.setScrollTop(wrap.scrollHeight)
  })
}

async function goDocuments() { router.push('/documents') }

// 组件被 keep-alive 保活，切回来时只刷新会话列表，当前会话和消息都还在
let restored = false

onMounted(async () => {
  await loadSessions()
  // 优先恢复上次在看的会话（否则切回来会跳到列表第一个，看起来像"串台"）
  const saved = sessionStorage.getItem(LAST_SESSION_KEY)
  const target = sessionList.value.find((s) => String(s.id) === saved) || sessionList.value[0]
  if (target) selectSession(target)
  restored = true
})

onActivated(() => {
  if (!restored) return   // 首次进入由 onMounted 负责
  loadSessions()          // 期间可能在文档页/别处新建或删除了会话
  scrollToBottom()
})

watch(currentSessionId, (id) => {
  if (id != null) sessionStorage.setItem(LAST_SESSION_KEY, String(id))
})
</script>

<template>
  <div class="chat-page">
    <!-- 会话列表 -->
    <el-card shadow="never" class="sessions" body-style="padding: 12px">
      <el-button type="primary" plain style="width: 100%" @click="newSession">
        <el-icon><Plus /></el-icon><span>新对话</span>
      </el-button>
      <el-input
        v-model="searchKey"
        placeholder="搜索会话"
        size="small"
        clearable
        class="search"
        :prefix-icon="'Search'"
      />
      <div class="session-list">
        <div v-if="!filteredSessions.length" class="empty-tip">
          <el-icon><Search /></el-icon>
          <span>暂无匹配的会话</span>
        </div>
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === currentSessionId }"
          @click="selectSession(s)"
        >
          <el-icon class="session-icon"><ChatDotRound /></el-icon>
          <div class="meta">
            <div class="title">{{ s.title }}</div>
            <div class="time mono">{{ fmtAgo(s.update_time) }}</div>
          </div>
          <el-button text size="small" class="del-btn" @click.stop="removeSession(s)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 消息区 -->
    <el-card shadow="never" class="chat-area" body-style="padding: 0; display: flex; flex-direction: column; height: 100%">
      <div class="chat-header">
        <span class="title">{{ currentTitle }}</span>
        <span class="stats mono">
          <span>{{ msgCount }} 条消息</span>
          <span v-if="sourceCount" class="dot" />
          <span v-if="sourceCount">引用 {{ sourceCount }} 处</span>
        </span>
      </div>

      <el-scrollbar ref="listRef" class="messages">
        <!-- 更早的消息被截断时给一个显式入口，点击一次全量加载 -->
        <div v-if="hasMore" class="load-older">
          <el-button text size="small" @click="loadAllMessages">
            <el-icon><Top /></el-icon>
            <span>还有 {{ hiddenCount }} 条更早的消息，点击全部加载</span>
          </el-button>
        </div>
        <!-- 空状态：给一个明确的可执行动作 -->
        <div v-if="!messages.length && !asking" class="chat-empty">
          <div class="empty-badge"><el-icon :size="30"><ChatDotRound /></el-icon></div>
          <p class="empty-title">{{ currentSessionId ? '这个会话还没有消息' : '还没有开始对话' }}</p>
          <p class="empty-sub">提问后会在你的文档里检索，并标注引用来源</p>
          <el-button v-if="!currentSessionId" type="primary" @click="newSession">
            <el-icon><Plus /></el-icon><span>开始新对话</span>
          </el-button>
          <el-button v-else type="primary" plain @click="goDocuments">
            <el-icon><Upload /></el-icon><span>去上传文档</span>
          </el-button>
        </div>

        <template v-else>
          <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
            <el-avatar v-if="m.role === 'assistant'" :size="34" class="avatar">AI</el-avatar>
            <div class="bubble-wrap">
              <div class="bubble">
                <div class="content">{{ m.content }}</div>
                <!-- 来源标注：只有真的检索到才显示，常识性问题不渲染成"失败"的样子 -->
                <div v-if="m.role === 'assistant' && m.sources?.length" class="sources">
                  <div class="src-badge">
                    <el-icon><Link /></el-icon>
                    <span>知识库检索 · {{ m.sources.length }} 处 / {{ srcDocCount(m.sources) }} 篇文档</span>
                  </div>
                  <el-collapse>
                    <el-collapse-item
                      v-for="(s, j) in m.sources" :key="j"
                      :title="`[${j + 1}] ${s.title} · 切片 ${s.chunk_index}`"
                      :name="String(j)"
                    >
                      <div class="source-content">{{ s.content }}</div>
                    </el-collapse-item>
                  </el-collapse>
                </div>
              </div>
              <div class="msg-meta">
                <span class="time mono">{{ fmtClock(m.creat_time) }}</span>
                <el-button v-if="m.role === 'assistant'" text size="small" class="copy-btn" @click="copyAnswer(m.content)">
                  <el-icon><CopyDocument /></el-icon><span>复制</span>
                </el-button>
              </div>
            </div>
            <el-avatar v-if="m.role === 'user'" :size="34" class="avatar user-avatar">我</el-avatar>
          </div>

          <div v-if="asking" class="msg-row assistant">
            <el-avatar :size="34" class="avatar">AI</el-avatar>
            <div class="bubble loading-bubble">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>正在检索文档并生成回答…</span>
            </div>
          </div>
        </template>
      </el-scrollbar>

      <div class="input-bar">
        <el-input
          ref="inputRef"
          v-model="question"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          maxlength="2000"
          resize="none"
          placeholder="输入问题，Enter 发送（Shift+Enter 换行）"
          :disabled="asking"
          @keydown.enter.exact.prevent="ask"
        />
        <el-button
          type="primary" :loading="asking" :disabled="!question.trim()"
          size="large" @click="ask"
        >
          <el-icon><Promotion /></el-icon><span>发送</span>
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
/* 铺满主区：高度由 flex 决定，不再依赖 calc(100vh - 60px) 这类魔法值 */
.chat-page { flex: 1; min-height: 0; display: flex; gap: 16px; }

.sessions { width: 236px; flex-shrink: 0; display: flex; flex-direction: column; }
.sessions :deep(.el-card__body) { display: flex; flex-direction: column; min-height: 0; }
.search { margin: 10px 0 6px; }
.session-list { flex: 1; min-height: 0; overflow-y: auto; margin: 0 -4px; padding: 0 4px; }
.empty-tip {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  color: var(--text-3); font-size: 12.5px; padding: 22px 0;
}
.session-item {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 10px; border-radius: 9px;
  cursor: pointer; margin-top: 4px;
  transition: background .15s, box-shadow .15s, color .15s;
}
.session-item:hover { background: rgba(120, 160, 220, 0.08); }
.session-item.active {
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.18), rgba(79, 140, 255, 0.05));
  color: var(--text-1);
  box-shadow: inset 2px 0 0 var(--accent-1);
}
.session-icon { color: var(--text-3); flex-shrink: 0; }
.session-item.active .session-icon { color: var(--accent-1); }
.session-item .meta { flex: 1; min-width: 0; }
.session-item .title {
  font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.session-item .time { font-size: 11px; color: var(--text-3); margin-top: 1px; }
.session-item .del-btn { color: var(--text-3); opacity: .45; transition: opacity .15s, color .15s; }
.session-item:hover .del-btn, .session-item.active .del-btn { opacity: 1; }
.session-item .del-btn:hover { color: #f56c6c; }

.chat-area { flex: 1; min-width: 0; overflow: hidden; }
.chat-header {
  display: flex; align-items: center; gap: 12px;
  padding: 13px 18px; border-bottom: 1px solid var(--line);
  font-size: 15px; font-weight: 600; color: var(--text-1);
}
.chat-header .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-header .stats {
  margin-left: auto; display: flex; align-items: center; gap: 8px;
  font-size: 11.5px; font-weight: 400; color: var(--text-3); flex-shrink: 0;
}
.chat-header .dot { width: 3px; height: 3px; border-radius: 50%; background: var(--text-3); }

.messages { flex: 1; min-height: 0; padding: 16px 18px; }
/* 滚动内容至少撑满容器，空状态才能垂直居中（父级高度是 auto，height:100% 会失效） */
.messages :deep(.el-scrollbar__view) { min-height: 100%; display: flex; flex-direction: column; }

/* 加载更早的消息 */
.load-older { display: flex; justify-content: center; padding-bottom: 12px; }
.load-older span { font-size: 12.5px; }

/* 空状态 */
.chat-empty {
  flex: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 4px; padding-bottom: 24px;
}
.empty-badge {
  width: 62px; height: 62px; margin-bottom: 12px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: var(--accent-1);
  background: radial-gradient(circle, rgba(34, 211, 238, .16), transparent 70%);
  border: 1px solid rgba(34, 211, 238, .26);
  box-shadow: 0 0 30px rgba(34, 211, 238, .16);
}
.empty-title { margin: 0; font-size: 14.5px; font-weight: 600; color: var(--text-1); }
.empty-sub { margin: 0 0 16px; font-size: 12.5px; color: var(--text-2); }

.msg-row { display: flex; gap: 10px; margin-bottom: 18px; align-items: flex-start; }
.msg-row.user { justify-content: flex-end; }
.avatar {
  background: var(--grad); color: var(--on-accent);
  flex-shrink: 0; font-size: 13px; font-weight: 700;
}
.user-avatar { background: linear-gradient(135deg, #4f8cff, #8b5cf6); color: #fff; }
.bubble-wrap { max-width: 72%; display: flex; flex-direction: column; gap: 4px; }
.bubble {
  padding: 12px 14px; border-radius: 12px;
  background: rgba(17, 25, 40, 0.72);
  border: 1px solid var(--line);
  color: var(--text-1);
  white-space: pre-wrap;
  word-break: break-word; line-height: 1.58;
}
.msg-row.user .bubble {
  background: var(--grad); color: var(--on-accent);
  border-color: transparent; font-weight: 500;
}
.msg-row.user .bubble :deep(.el-divider__text) { color: rgba(5, 18, 29, .8); }
.msg-meta { display: flex; align-items: center; gap: 6px; padding: 0 4px; min-height: 20px; }
.msg-row.user .msg-meta { justify-content: flex-end; }
.msg-meta .time { font-size: 11px; color: var(--text-3); }
.copy-btn { color: var(--text-3); opacity: .7; }
.copy-btn:hover { opacity: 1; color: var(--accent-1); }
.sources { margin-top: 4px; white-space: normal; }
.src-badge {
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: 10px; padding: 3px 9px;
  border-radius: 999px;
  font-size: 11.5px; line-height: 1.7;
  color: var(--accent-1);
  background: rgba(34, 211, 238, .09);
  border: 1px solid rgba(34, 211, 238, .22);
}
.source-content { color: var(--text-2); font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.loading-bubble {
  display: flex; align-items: center; gap: 8px;
  background: rgba(17, 25, 40, 0.72);
  border: 1px solid var(--line);
  padding: 10px 14px;
  border-radius: 12px; color: var(--accent-1); font-size: 13px;
}
.input-bar {
  display: flex; gap: 12px; align-items: flex-end;
  padding: 14px 18px; border-top: 1px solid var(--line);
  background: rgba(10, 16, 28, 0.66);
  backdrop-filter: blur(10px);
}
.input-bar :deep(.el-textarea__inner) { padding: 8px 12px; line-height: 1.55; }
</style>
