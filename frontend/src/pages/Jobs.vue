<template>
  <div class="container">
    <div class="jobs-panel">
      <div class="panel-header">
        <h2>My Uploads</h2>
        <button @click="refresh" class="btn-icon" title="Refresh" :disabled="loading">
          ↻
        </button>
      </div>

      <div v-if="loading" class="loading">Loading jobs...</div>
      <div v-else-if="jobs.length === 0" class="empty">
        <div class="empty-icon">📭</div>
        <p>No upload jobs yet</p>
      </div>
      <div v-else class="table-wrapper">
        <table class="jobs-table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Status</th>
              <th>File</th>
              <th>Namespace</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.job_id">
              <td class="job-id" :title="job.job_id">{{ shortId(job.job_id) }}</td>
              <td>
                <span class="status-badge" :class="statusClass(job.status)">{{ job.status }}</span>
              </td>
              <td class="job-file">{{ job.filename || '—' }}</td>
              <td>{{ job.namespace || '—' }}</td>
              <td class="job-date">{{ formatDate(job.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { listJobs, pollJob } from '../api/client.js'

const TERMINAL = ['done', 'skipped', 'failed', 'cancelled']

const loading = ref(true)
const jobs = ref([])

// Track active polls so we can stop updating after the component unmounts.
let unmounted = false
const activePolls = new Set()

const shortId = (id) => (id ? String(id).slice(0, 8) : '—')

const statusClass = (status) => {
  if (status === 'done' || status === 'skipped') return 'status-done'
  if (status === 'failed' || status === 'cancelled') return 'status-failed'
  return 'status-pending'
}

const formatDate = (dateStr) => {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  return Number.isNaN(date.getTime()) ? dateStr : date.toLocaleString()
}

// Live-update a single in-flight job's row via smart-poll.
const watchJob = (job) => {
  if (activePolls.has(job.job_id)) return
  activePolls.add(job.job_id)
  pollJob(job.job_id, {
    onUpdate: (updated) => {
      if (unmounted) return
      const idx = jobs.value.findIndex(j => j.job_id === updated.job_id)
      if (idx !== -1) {
        jobs.value[idx] = { ...jobs.value[idx], ...updated }
      }
    }
  })
    .catch(() => { /* timeout or network error: leave last known state */ })
    .finally(() => { activePolls.delete(job.job_id) })
}

const load = async () => {
  loading.value = true
  try {
    const response = await listJobs()
    jobs.value = response.jobs || []
    // Start live polling for any non-terminal jobs.
    for (const job of jobs.value) {
      if (!TERMINAL.includes(job.status)) watchJob(job)
    }
  } catch (error) {
    console.error('Failed to load jobs:', error)
    jobs.value = []
  } finally {
    loading.value = false
  }
}

const refresh = () => load()

onMounted(() => {
  load()
})

onUnmounted(() => {
  // Mirror App.vue's cleanup pattern: stop applying poll updates after unmount.
  unmounted = true
  activePolls.clear()
})
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
}

.jobs-panel {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
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

.table-wrapper {
  overflow-x: auto;
}

.jobs-table {
  width: 100%;
  border-collapse: collapse;
}

.jobs-table th {
  text-align: left;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  padding: 0.75rem 1rem;
  border-bottom: 2px solid #e5e7eb;
}

.jobs-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e7eb;
  color: #374151;
  font-size: 0.9rem;
}

.jobs-table tbody tr:last-child td {
  border-bottom: none;
}

.jobs-table tbody tr:hover {
  background: #f9fafb;
}

.job-id {
  font-family: monospace;
  color: #6b7280;
}

.job-file {
  font-weight: 500;
  word-break: break-all;
}

.job-date {
  color: #9ca3af;
  white-space: nowrap;
}

.status-badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: capitalize;
}

.status-done {
  background: #d1fae5;
  color: #065f46;
}

.status-failed {
  background: #fee2e2;
  color: #991b1b;
}

.status-pending {
  background: #dbeafe;
  color: #1e40af;
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

.empty {
  text-align: center;
  padding: 3rem 2rem;
  color: #9ca3af;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

/* Mobile breakpoint */
@media (max-width: 768px) {
  .container {
    padding: 0 1rem;
  }

  .jobs-panel {
    padding: 1.25rem;
  }

  .panel-header h2 {
    font-size: 1.25rem;
  }

  .jobs-table th,
  .jobs-table td {
    padding: 0.5rem 0.6rem;
    font-size: 0.85rem;
  }
}
</style>
