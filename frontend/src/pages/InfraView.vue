<template>
  <div class="infra-view">
    <PageHeader title="基础设施" :loading="loading" :show-border="true">
      <template #actions>
        <a-button type="text" :loading="loading" @click="refreshAll">
          <template #icon><RefreshCw class="action-icon" /></template>
          刷新
        </a-button>
      </template>
    </PageHeader>

    <div class="infra-body">
      <a-alert
        type="info"
        show-icon
        class="top-alert"
        message="前后端分离部署"
        description="前端可构建一次后部署到任意机器，只需在部署时指定后端地址；后台服务器专跑 Docker 容器。下方连接地址决定平台连到哪台机器上的哪个服务，保存后立即生效，无需重启。"
      />

      <!-- 服务状态 -->
      <section class="section">
        <div class="section-header">
          <h2 class="section-title">服务状态</h2>
          <span class="section-desc">按当前生效的连接地址探测可达性</span>
        </div>

        <a-spin :spinning="loading">
          <div class="service-grid">
            <a-card
              v-for="svc in services"
              :key="svc.name"
              size="small"
              class="service-card"
              :class="{ 'service-card--healthy': svc.status === 'healthy' }"
            >
              <template #title>
                <div class="service-title">
                  <span class="service-name">{{ svc.service }}</span>
                  <a-tag :color="statusColor(svc.status)" class="service-tag">
                    {{ statusText(svc.status) }}
                  </a-tag>
                </div>
              </template>

              <div class="service-meta">
                <div class="service-row">
                  <span class="service-key">地址</span>
                  <code class="service-value service-value--wrap">{{ svc.endpoint || '未配置' }}</code>
                </div>
                <div class="service-row">
                  <span class="service-key">来源</span>
                  <span class="service-value">{{ sourceText(svc.source) }}</span>
                </div>
                <div class="service-row">
                  <span class="service-key">探测</span>
                  <span class="service-value">{{ svc.detail || '—' }}</span>
                </div>
              </div>
            </a-card>
          </div>
          <a-empty
            v-if="!loading && services.length === 0"
            description="没有可管理的服务"
            class="service-empty"
          />
        </a-spin>
      </section>

      <!-- 连接地址 -->
      <section class="section">
        <div class="section-header">
          <h2 class="section-title">连接地址</h2>
          <span class="section-desc">
            可编辑项保存到数据库并立即生效；部署期项由服务器环境变量决定
          </span>
        </div>

        <a-card size="small" class="connection-card">
          <a-form layout="vertical" class="connection-form">
            <a-row :gutter="16">
              <a-col v-for="item in editableConnections" :key="item.key" :xs="24" :md="12">
                <a-form-item :label="item.label">
                  <a-input
                    v-model:value="draft[item.field]"
                    :placeholder="item.placeholder"
                    allow-clear
                  />
                  <div class="field-hint">
                    <span>{{ item.service }}</span>
                    <span class="field-hint-dot">·</span>
                    <span>当前生效：{{ item.value || '未配置' }}</span>
                  </div>
                </a-form-item>
              </a-col>
            </a-row>

            <div class="connection-actions">
              <a-button type="primary" :loading="saving" @click="handleSave">保存连接地址</a-button>
              <a-button :disabled="saving" @click="loadConnections">重新读取</a-button>
            </div>
          </a-form>
        </a-card>
      </section>

      <!-- 部署期配置 -->
      <section class="section">
        <div class="section-header">
          <h2 class="section-title">部署期配置</h2>
          <span class="section-desc">由服务器部署环境提供，修改需改环境变量并重启 api/worker</span>
        </div>

        <a-card size="small" class="connection-card">
          <a-descriptions bordered size="small" :column="1">
            <a-descriptions-item
              v-for="item in readonlyConnections"
              :key="item.key"
              :label="item.label"
            >
              <code class="service-value service-value--wrap">{{ item.value || '未配置' }}</code>
              <div class="field-hint">{{ item.reason }}</div>
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { RefreshCw } from '@lucide/vue'

import PageHeader from '@/shared/ui/PageHeader.vue'
import { infrastructureApi } from '@/apis/infrastructure_api'

const loading = ref(false)
const saving = ref(false)
const connections = ref([])
const draft = ref({})

// 后端 option 字段名 → 环境变量键，用于在表单与后端契约之间转换。
const FIELD_BY_KEY = {
  MINIO_URI: 'minio_uri',
  MILVUS_URI: 'milvus_uri',
  NEO4J_URI: 'neo4j_uri',
  SANDBOX_RUNNER_URL: 'sandbox_runner_url'
}

const editableConnections = computed(() =>
  connections.value
    .filter((item) => item.editable)
    .map((item) => ({
      ...item,
      field: FIELD_BY_KEY[item.key] || item.key
    }))
)

const readonlyConnections = computed(() => connections.value.filter((item) => !item.editable))

const services = computed(() =>
  connections.value.map((item) => ({
    name: item.key,
    service: item.service,
    label: item.label,
    endpoint: item.value,
    source: item.source,
    status: item.status,
    detail: item.detail
  }))
)

const statusText = (status) => {
  if (status === 'healthy') return '可达'
  if (status === 'unreachable') return '不可达'
  if (status === 'unconfigured') return '未配置'
  return '未知'
}

const statusColor = (status) => {
  if (status === 'healthy') return 'green'
  if (status === 'unreachable') return 'red'
  if (status === 'unconfigured') return 'default'
  return 'blue'
}

const sourceText = (source) => {
  if (source === 'database') return '页面配置'
  if (source === 'environment') return '部署环境'
  return '默认值'
}

const loadConnections = async () => {
  const data = await infrastructureApi.getConnections()
  connections.value = data?.connections || []
  const next = {}
  for (const item of connections.value) {
    const field = FIELD_BY_KEY[item.key]
    if (!field) continue
    next[field] = item.stored || ''
  }
  draft.value = next
}

const refreshAll = async () => {
  loading.value = true
  try {
    await infrastructureApi.refreshConnections()
    await loadConnections()
  } catch (error) {
    message.error(error?.message || '加载基础设施状态失败')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const values = {}
    for (const item of editableConnections.value) {
      values[item.field] = draft.value[item.field] || ''
    }
    const result = await infrastructureApi.saveConnections(values)
    connections.value = result?.connections || connections.value
    message.success('连接地址已保存并生效')
  } catch (error) {
    message.error(error?.message || '保存连接地址失败')
  } finally {
    saving.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped lang="less">
.infra-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background-color: var(--gray-30);
}

.action-icon {
  width: 14px;
  height: 14px;
}

.infra-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px var(--page-padding) 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.top-alert {
  border-radius: 8px;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
}

.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-1000);
}

.section-desc {
  font-size: 12px;
  color: var(--gray-600);
}

.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.service-card {
  border-radius: 8px;
  border: 1px solid var(--gray-100);
}

.service-card--healthy {
  border-color: var(--color-primary-500);
}

.service-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.service-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--gray-1000);
}

.service-tag {
  margin-inline-end: 0;
}

.service-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.service-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
}

.service-key {
  flex: 0 0 40px;
  color: var(--gray-600);
}

.service-value {
  flex: 1;
  min-width: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--gray-1000);
  word-break: break-all;
}

.service-empty {
  background-color: var(--gray-0);
  border-radius: 8px;
}

.connection-card {
  border-radius: 8px;
}

.connection-form :deep(.ant-form-item) {
  margin-bottom: 16px;
}

.field-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--gray-600);
}

.field-hint-dot {
  margin: 0 6px;
}

.connection-actions {
  display: flex;
  gap: 8px;
  padding-top: 4px;
}
</style>
