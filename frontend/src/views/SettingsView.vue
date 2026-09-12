<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi, parseError } from '../api'
import PageHeader from '../components/PageHeader.vue'

const loading = ref(false)
const saving = ref(false)
const historyLimit = ref(10)
const defaultLimit = ref(10)

const presets = [
  { key: 'short', label: '短（1~3）', value: 3, desc: '只记最近几轮，省 token，适合简单问答' },
  { key: 'medium', label: '中（10）', value: 10, desc: '平衡连贯性和成本，默认推荐' },
  { key: 'long', label: '长（30~50）', value: 30, desc: '上下文强连贯，适合长对话/复杂追问' },
]

// 与滑块双向联动：拖到某个预设值就自动高亮对应的档位
const preset = computed(() => presets.find((p) => p.value === historyLimit.value)?.key || '')

const scenario = computed(() => {
  if (historyLimit.value <= 3) {
    return { icon: 'InfoFilled', color: '#f0b429', text: '上下文较短：token 消耗低，但早期信息容易丢' }
  }
  if (historyLimit.value <= 15) {
    return { icon: 'CircleCheck', color: 'var(--accent-1)', text: '日常对话推荐：连贯性与成本比较平衡' }
  }
  return { icon: 'WarningFilled', color: '#f56c6c', text: '上下文较长：连贯性强，token 消耗明显上升' }
})

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await settingsApi.get()
    historyLimit.value = data.history_limit
    defaultLimit.value = data.default_history_limit
  } catch (e) { ElMessage.error(parseError(e)) }
  finally { loading.value = false }
})

async function save() {
  saving.value = true
  try {
    const { data } = await settingsApi.updateHistoryLimit(historyLimit.value)
    historyLimit.value = data.history_limit
    ElMessage.success('已保存，下次提问生效')
  } catch (e) { ElMessage.error(parseError(e)) }
  finally { saving.value = false }
}

async function reset() {
  saving.value = true
  try {
    const { data } = await settingsApi.updateHistoryLimit(null)
    historyLimit.value = data.history_limit
    ElMessage.success('已重置为全局默认')
  } catch (e) { ElMessage.error(parseError(e)) }
  finally { saving.value = false }
}

function applyPreset(key) {
  const p = presets.find((x) => x.key === key)
  if (p) historyLimit.value = p.value
}
</script>

<template>
  <div class="settings-page">
    <PageHeader title="设置" subtitle="设置只对你自己的账号生效，保存后下次提问时使用">
      <el-button :disabled="saving" @click="reset">
        <el-icon><RefreshLeft /></el-icon><span>重置为默认</span>
      </el-button>
    </PageHeader>

    <el-card v-loading="loading" shadow="never">
      <template #header>
        <div class="card-header">
          <el-icon><ChatLineSquare /></el-icon><span>对话记忆长度</span>
        </div>
      </template>

      <div class="limit-block">
        <div class="limit-value">
          <span class="num grad-text">{{ historyLimit }}</span>
          <span class="unit">条</span>
        </div>
        <div class="limit-slider">
          <el-slider v-model="historyLimit" :min="1" :max="50" :step="1" show-stops />
          <div class="scale mono"><span>1</span><span>50</span></div>
        </div>
      </div>

      <div class="preset-row">
        <span class="row-label">快速设置</span>
        <el-radio-group :model-value="preset" @change="applyPreset">
          <el-tooltip v-for="p in presets" :key="p.key" :content="p.desc" placement="top">
            <el-radio-button :value="p.key">{{ p.label }}</el-radio-button>
          </el-tooltip>
        </el-radio-group>
      </div>

      <div class="status-line">
        <el-icon class="status-icon" :style="{ color: scenario.color }"><component :is="scenario.icon" /></el-icon>
        <span>{{ scenario.text }}</span>
      </div>
      <div class="status-line sub">
        <span>参与答案生成的历史消息条数：当前 <b class="mono">{{ historyLimit }}</b> 条，全局默认 <b class="mono">{{ defaultLimit }}</b> 条</span>
      </div>

      <div class="actions">
        <el-button type="primary" :loading="saving" @click="save">
          <el-icon><Check /></el-icon><span>保存</span>
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="about-card">
      <template #header>
        <div class="card-header">
          <el-icon><InfoFilled /></el-icon><span>关于</span>
        </div>
      </template>
      <div class="about-row">
        <span class="k">项目</span>
        <span class="v">rag_doc_agent · 基于 FastAPI + RAG 的多租户智能知识库</span>
      </div>
      <div class="about-row">
        <span class="k">存储</span>
        <span class="v">保存后写入 <code>users.history_limit</code>，下次提问生效</span>
      </div>
      <div class="about-row">
        <span class="k">默认值</span>
        <span class="v">重置（传 null）会回到全局 <code>SESSION_HISTORY_LIMIT</code></span>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.settings-page { display: flex; flex-direction: column; max-width: 780px; }

.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.card-header .el-icon { color: var(--accent-1); }

.limit-block { display: flex; align-items: center; gap: 26px; margin: 6px 0 22px; }
.limit-value { display: flex; align-items: baseline; gap: 4px; flex-shrink: 0; }
.limit-value .num {
  font-family: var(--mono);
  font-size: 40px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.limit-value .unit { font-size: 13px; color: var(--text-2); }
.limit-slider { flex: 1; min-width: 0; padding-right: 8px; }
.scale {
  display: flex; justify-content: space-between;
  margin-top: 2px; font-size: 11px; color: var(--text-3);
}

.preset-row { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.row-label { font-size: 13px; color: var(--text-2); flex-shrink: 0; }

.status-line {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text-1);
  margin-bottom: 6px;
}
.status-line.sub { color: var(--text-2); font-size: 12.5px; }
.status-icon { flex-shrink: 0; }
.status-line b { color: var(--text-1); font-weight: 600; }

.actions { margin-top: 18px; display: flex; gap: 10px; }

.about-card { margin-top: 16px; }
.about-row { display: flex; gap: 14px; margin: 8px 0; font-size: 13px; }
.about-row .k { width: 62px; flex-shrink: 0; color: var(--text-3); }
.about-row .v { color: var(--text-2); }
.about-row code {
  background: rgba(34, 211, 238, 0.1);
  color: #7ee7ff;
  font-family: var(--mono);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
