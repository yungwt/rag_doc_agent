<script setup>
// 页面统一头部：左侧标题+副标题（标题前有一条渐变竖条），右侧放操作按钮/统计
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<template>
  <header class="page-header">
    <div class="ph-main">
      <h2 class="ph-title">{{ title }}</h2>
      <p v-if="subtitle" class="ph-sub">{{ subtitle }}</p>
    </div>
    <div class="ph-extra"><slot /></div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 16px;
  flex-shrink: 0;
}
.ph-main { min-width: 0; }
.ph-title {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: .3px;
  color: var(--text-1);
}
.ph-title::before {
  content: '';
  width: 3px;
  height: 15px;
  border-radius: 2px;
  background: var(--grad);
  box-shadow: 0 0 10px rgba(34, 211, 238, .5);
}
.ph-sub {
  margin: 5px 0 0 12px;
  font-size: 12.5px;
  letter-spacing: .2px;
  color: var(--text-2);
}
.ph-extra {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
