<template>
  <div class="container">
    <div class="account-panel">
      <div class="panel-header">
        <h2>Account &amp; Usage</h2>
        <button
          v-if="!loading"
          @click="refresh"
          class="btn-icon"
          title="Refresh"
          :disabled="loading"
        >
          ↻
        </button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="loading">Loading usage…</div>

      <!-- No extension API on this deployment: plans/usage do not exist here.
           A normal core-only install, so no retry button — it cannot succeed. -->
      <div v-else-if="unavailable" class="state-message">
        <div class="state-icon">📊</div>
        <p>Usage tracking isn't enabled on this deployment.</p>
        <p class="state-sub">Plans and usage limits are unavailable here.</p>
      </div>

      <!-- Access denied (403): authenticated but not permitted for this account -->
      <div v-else-if="accessDenied" class="state-message">
        <div class="state-icon">🔒</div>
        <p>You don't have access to this account's usage.</p>
        <p class="state-sub">This page is available to account administrators.</p>
      </div>

      <!-- Generic error -->
      <div v-else-if="error" class="state-message">
        <div class="state-icon">⚠️</div>
        <p>We couldn't load your usage right now.</p>
        <button @click="refresh" class="btn-retry">Try again</button>
      </div>

      <!-- Loaded -->
      <template v-else>
        <div class="plan-card">
          <span class="plan-label">Current plan</span>
          <span class="plan-name">{{ planDisplay }}</span>
        </div>

        <div v-if="metrics.length === 0" class="state-message">
          <div class="state-icon">📊</div>
          <p>No usage data yet.</p>
          <p class="state-sub">Usage will appear here once you start using Stache.</p>
        </div>

        <ul v-else class="usage-list">
          <li v-for="item in metrics" :key="item.metric" class="usage-item">
            <div class="usage-top">
              <div class="usage-label">
                {{ item.label }}
                <span v-if="item.period" class="usage-period">{{ item.period }}</span>
              </div>
              <div class="usage-values">
                <span class="usage-used">{{ item.usedDisplay }}</span>
                <span class="usage-sep">/</span>
                <span class="usage-limit">{{ item.limitDisplay }}</span>
              </div>
            </div>
            <div class="progress-track" :class="{ unlimited: item.unlimited }">
              <div
                v-if="!item.unlimited"
                class="progress-fill"
                :class="item.severity"
                :style="{ width: item.percent + '%' }"
              ></div>
            </div>
          </li>
        </ul>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getAccountUsage } from '../api/client.js'

// Friendly labels for the canonical metrics. Monthly metrics get the period
// appended alongside their "this month" phrasing. Unknown metric names fall
// back to a titleized version so a new backend metric still renders.
const METRIC_LABELS = {
  documents: 'Documents',
  storage_bytes: 'Storage',
  queries: 'Queries this month',
  // NOT "tokens". The backend reports this as an internal, normalized unit --
  // an expensive model's tokens weigh more than a cheap one's -- so the raw
  // number is not a token count and must not be shown to a user as one. The
  // percentage is the meaningful figure; keeping the unit abstract also lets
  // the underlying models change without the displayed number changing meaning.
  bedrock_tokens: 'AI usage this month',
}

const BYTE_METRICS = new Set(['storage_bytes'])

const loading = ref(true)
const error = ref(false)
const accessDenied = ref(false)
const unavailable = ref(false)
const plan = ref(null)
const usage = ref([])

const planDisplay = computed(() => plan.value || '—')

const titleize = (s) =>
  String(s)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

const formatBytes = (bytes) => {
  if (bytes === null || bytes === undefined) return '—'
  const n = Number(bytes)
  if (!Number.isFinite(n)) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB', 'PB']
  let value = n / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  // One decimal place, but drop a trailing .0 for clean whole values.
  const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${units[i]}`
}

const formatCount = (n) => {
  const v = Number(n)
  return Number.isFinite(v) ? v.toLocaleString() : '—'
}

const metrics = computed(() =>
  (usage.value || []).map((item) => {
    const isBytes = BYTE_METRICS.has(item.metric)
    const format = isBytes ? formatBytes : formatCount
    const limit = item.quota_limit
    const unlimited = limit === null || limit === undefined
    const used = Number(item.usage_count) || 0

    let percent = 0
    let severity = 'ok'
    if (!unlimited && Number(limit) > 0) {
      percent = Math.min(100, Math.round((used / Number(limit)) * 100))
      if (percent >= 90) severity = 'danger'
      else if (percent >= 75) severity = 'warn'
    }

    return {
      metric: item.metric,
      label: METRIC_LABELS[item.metric] || titleize(item.metric),
      period: item.period || null,
      unlimited,
      percent,
      severity,
      usedDisplay: format(used),
      limitDisplay: unlimited ? 'Unlimited' : format(limit),
    }
  })
)

const load = async () => {
  loading.value = true
  error.value = false
  accessDenied.value = false
  unavailable.value = false
  try {
    const data = await getAccountUsage()
    plan.value = data?.plan ?? null
    usage.value = Array.isArray(data?.usage) ? data.usage : []
  } catch (err) {
    // No extension API on this deployment: plans and usage simply do not exist
    // here. That is a normal core-only install, not a failure — say so, and do
    // not offer a retry that cannot succeed.
    if (err?.isExtensionUnavailable) {
      unavailable.value = true
    // 401 is already handled globally by the client interceptor (re-login
    // redirect). 403 means authenticated-but-not-permitted — a retry won't
    // help, so show a distinct message. Everything else gets a generic,
    // retryable error and never surfaces the raw response body.
    } else if (err?.status === 403) {
      accessDenied.value = true
    } else if (err?.status !== 401) {
      error.value = true
    }
    plan.value = null
    usage.value = []
  } finally {
    loading.value = false
  }
}

const refresh = () => load()

onMounted(load)
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
}

.account-panel {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  padding: 2rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.panel-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: #1f2937;
}

.plan-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 1.25rem 1.5rem;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  margin-bottom: 2rem;
}

.plan-label {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.85;
}

.plan-name {
  font-size: 1.75rem;
  font-weight: 700;
  text-transform: capitalize;
}

.usage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.usage-item {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.usage-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
}

.usage-label {
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.usage-period {
  font-size: 0.7rem;
  font-weight: 500;
  color: #6b7280;
  background: #f3f4f6;
  padding: 0.1rem 0.5rem;
  border-radius: 9999px;
}

.usage-values {
  font-size: 0.9rem;
  color: #374151;
  white-space: nowrap;
}

.usage-used {
  font-weight: 600;
}

.usage-sep {
  color: #9ca3af;
  margin: 0 0.35rem;
}

.usage-limit {
  color: #6b7280;
}

.progress-track {
  height: 8px;
  border-radius: 9999px;
  background: #e5e7eb;
  overflow: hidden;
}

.progress-track.unlimited {
  background: repeating-linear-gradient(
    45deg,
    #eef2ff,
    #eef2ff 6px,
    #e5e7eb 6px,
    #e5e7eb 12px
  );
}

.progress-fill {
  height: 100%;
  border-radius: 9999px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  transition: width 0.4s ease;
}

.progress-fill.warn {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.progress-fill.danger {
  background: linear-gradient(135deg, #f87171 0%, #dc2626 100%);
}

.btn-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: white;
  font-size: 1.2rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover:not(:disabled) {
  background: #f3f4f6;
}

.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading {
  text-align: center;
  padding: 2rem;
  color: #9ca3af;
}

.state-message {
  text-align: center;
  padding: 3rem 2rem;
  color: #9ca3af;
}

.state-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.state-sub {
  font-size: 0.85rem;
  margin-top: 0.35rem;
}

.btn-retry {
  margin-top: 1rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 0.6rem 1.5rem;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-retry:hover {
  opacity: 0.92;
}

/* Mobile breakpoint */
@media (max-width: 768px) {
  .container {
    padding: 0 1rem;
  }

  .account-panel {
    padding: 1.25rem;
  }

  .panel-header h2 {
    font-size: 1.25rem;
  }

  .plan-name {
    font-size: 1.4rem;
  }
}
</style>
