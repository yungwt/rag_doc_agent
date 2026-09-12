<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { documents, parseError } from '../api'
import PageHeader from '../components/PageHeader.vue'

const docs = ref([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const filter = ref('all')   // all / completed / processing / failed
const page = ref(1)
const pageSize = ref(10)
const dragging = ref(false)
let pollTimer = null

async function load() {
  loading.value = true
  try {
    const { data } = await documents.list((page.value - 1) * pageSize.value, pageSize.value, filter.value)
    docs.value = data.documents
    total.value = data.total
    // 删掉了当前页最后一条时往回退一页，避免停在空页上
    if (!docs.value.length && page.value > 1) {
      page.value -= 1
      loading.value = false
      return load()
    }
    if (data.documents.some((d) => ['uploading', 'processing'].includes(d.status)) && !pollTimer) {
      pollTimer = setTimeout(refresh, 3000)
    }
  } catch (e) {
    ElMessage.error(parseError(e))
  } finally {
    loading.value = false
  }
}

function refresh() { pollTimer = null; load() }

// 切筛选回到第 1 页重新请求（筛选已改为服务端过滤）
watch(filter, () => { page.value = 1; load() })

async function uploadFile(file) {
  if (!file) return
  uploading.value = true
  try {
    await documents.upload(file)
    ElMessage.success('已上传，正在后台解析')
    page.value = 1   // 新文档排在最前，回到第 1 页就能看到
    load()
  } catch (e) {
    ElMessage.error(parseError(e))
  } finally {
    uploading.value = false
  }
}

// el-upload 的 change 事件第一个参数就是 UploadFile 本身（原生文件在 .raw），没有 file 字段
function onFileChange(file) { uploadFile(file.raw ?? file) }

function onDrop(e) {
  e.preventDefault()
  dragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) uploadFile(file)
}

async function remove(doc) {
  try {
    await documents.remove(doc.id)
    ElMessage.success(`已删除：${doc.title}`)
    load()
  } catch (e) {
    ElMessage.error(parseError(e))
  }
}

const statusMap = {
  uploading: { text: '上传中', type: 'info', icon: 'Upload' },
  processing: { text: '处理中', type: 'warning', icon: 'Loading' },
  completed: { text: '已完成', type: 'success', icon: 'CircleCheck' },
  failed: { text: '失败', type: 'danger', icon: 'CircleClose' },
}

function fmtSize(b) {
  if (!b) return '-'
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(2) + ' MB'
}

load()
onUnmounted(() => pollTimer && clearTimeout(pollTimer))
</script>

<template>
  <div class="docs-page">
    <PageHeader title="文档管理" subtitle="上传后自动切分并向量化，问答时会从这些文档里检索">
      <span class="count mono">共 {{ total }} 个</span>
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon><span>刷新</span>
      </el-button>
    </PageHeader>

    <!-- 上传区 -->
    <el-card shadow="never" class="upload-card" v-loading="uploading">
      <div
        class="dropzone"
        :class="{ active: dragging }"
        @dragenter.prevent="dragging = true"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop="onDrop"
      >
        <div class="dz-badge"><el-icon :size="24"><UploadFilled /></el-icon></div>
        <div class="dz-text">
          <p class="dz-title">把文件拖到这里</p>
          <p class="dz-sub">支持 PDF / TXT / MD</p>
        </div>
        <el-upload
          class="dz-upload"
          :show-file-list="false"
          accept=".pdf,.txt,.md"
          :auto-upload="false"
          @change="onFileChange"
        >
          <el-button type="primary" size="large">
            <el-icon><Upload /></el-icon><span>选择文件</span>
          </el-button>
        </el-upload>
      </div>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never" class="list-card">
      <div class="toolbar">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="completed">已完成</el-radio-button>
          <el-radio-button value="processing">处理中</el-radio-button>
          <el-radio-button value="failed">失败</el-radio-button>
        </el-radio-group>
      </div>

      <el-empty v-if="!loading && !docs.length" :description="filter === 'all' ? '还没有文档，先上传一个吧' : '没有符合筛选条件的文档'" />
      <el-table v-else v-loading="loading" :data="docs" stripe>
        <el-table-column label="标题" min-width="240" sortable :sort-method="(a, b) => a.title.localeCompare(b.title)">
          <template #default="{ row }">
            <div class="title-cell">
              <el-icon class="file-icon"><Document /></el-icon>
              <div class="title-main">
                <span class="doc-title">{{ row.title }}</span>
                <!-- 解析失败时把后端给的原因显示出来，超长省略、悬停看全文 -->
                <span
                  v-if="row.status === 'failed' && row.error_message"
                  class="doc-error"
                  :title="row.error_message"
                >{{ row.error_message }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="86" align="center" />
        <el-table-column prop="file_size" label="大小" width="110" align="right" sortable>
          <template #default="{ row }"><span class="mono">{{ fmtSize(row.file_size) }}</span></template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="切片数" width="100" align="right" sortable>
          <template #default="{ row }"><span class="mono">{{ row.chunk_count }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="130" align="center">
          <template #default="{ row }">
            <el-tag class="status-tag" :type="statusMap[row.status]?.type || 'info'" effect="light">
              <span>{{ statusMap[row.status]?.text || row.status }}</span>
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-popconfirm
              :title="`确定删除「${row.title}」？向量数据会一并清除`"
              confirm-button-text="删除"
              cancel-button-text="取消"
              placement="top-end"
              @confirm="remove(row)"
            >
              <template #reference>
                <el-button text type="danger">
                  <el-icon><Delete /></el-icon><span>删除</span>
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <!-- 服务端分页 -->
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="total"
          background
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="() => { page = 1; load() }"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.docs-page { display: flex; flex-direction: column; }
.count { font-size: 12.5px; color: var(--text-2); margin-right: 4px; }

.upload-card { margin-bottom: 16px; }
.dropzone {
  display: flex; align-items: center; gap: 16px;
  padding: 18px 20px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: rgba(120, 160, 220, 0.03);
  color: var(--text-2);
  transition: all .18s;
}
.dropzone.active {
  border-color: var(--accent-1);
  background: rgba(34, 211, 238, 0.08);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.08), 0 8px 24px rgba(34, 211, 238, 0.12);
}
.dz-badge {
  width: 46px; height: 46px; flex-shrink: 0;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  color: var(--accent-1);
  background: rgba(34, 211, 238, 0.1);
  border: 1px solid rgba(34, 211, 238, 0.22);
}
.dropzone.active .dz-badge { box-shadow: 0 0 20px rgba(34, 211, 238, .3); }
.dz-text { flex: 1; min-width: 0; }
.dz-title { margin: 0; font-size: 14.5px; font-weight: 600; color: var(--text-1); }
.dz-sub { margin: 3px 0 0; font-size: 12.5px; color: var(--text-2); }

.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.title-cell { display: flex; align-items: center; gap: 8px; min-width: 0; }
.file-icon { color: var(--accent-1); flex-shrink: 0; }
.title-main { min-width: 0; }
.doc-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-error {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-color-danger, #f56c6c);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: default;
}
/* 状态徽章前的发光小圆点，用当前标签色 */
.status-tag::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px currentColor;
  display: inline-block;
  margin-right: 6px;
}
</style>
