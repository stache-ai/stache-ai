<template>
  <div class="trash-page">
    <div class="container">
      <div class="page-header">
        <h1>🗑️ Trash</h1>
        <p class="subtitle">
          Documents deleted within the last 30 days. Auto-purge after retention period.
        </p>
      </div>

      <!-- Filter Controls -->
      <div class="filters-bar" v-if="!loading && documents.length > 0">
        <div class="namespace-filter-wrapper">
          <label for="namespace-filter">Filter by Namespace:</label>
          <select v-model="selectedNamespace" id="namespace-filter" class="namespace-select" @change="loadTrash">
            <option value="">All Namespaces</option>
            <option v-for="ns in uniqueNamespaces" :key="ns" :value="ns">
              {{ ns || 'default' }}
            </option>
          </select>
        </div>
        <div class="filter-actions">
          <button
            @click="confirmEmptyTrash"
            class="btn-empty-trash"
            :disabled="filteredDocuments.length === 0 || emptyingTrash"
          >
            {{ emptyingTrash ? 'Emptying...' : 'Empty Trash' }}
            <span v-if="filteredDocuments.length > 0" class="doc-count">({{ filteredDocuments.length }})</span>
          </button>
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="loading && documents.length === 0" class="loading-state">
        <p>Loading trash...</p>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="error-state">
        <p class="error-message">{{ error }}</p>
        <button @click="loadTrash" class="btn-primary">Retry</button>
      </div>

      <!-- Empty State -->
      <div v-else-if="documents.length === 0" class="empty-state">
        <p>Trash is empty</p>
        <p class="hint">Deleted documents appear here and are automatically purged after 30 days</p>
      </div>

      <!-- Trash Table -->
      <div v-else class="trash-table-container">
        <table class="trash-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Namespace</th>
              <th>Deleted</th>
              <th>Purge Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in filteredDocuments" :key="`${doc.doc_id}-${doc.deleted_at_ms}`">
              <td class="filename-cell">
                <span class="filename">{{ doc.filename || 'Untitled' }}</span>
              </td>
              <td>
                <span class="namespace-badge">{{ doc.namespace || 'default' }}</span>
              </td>
              <td class="deleted-date">
                <time :datetime="doc.deleted_at">
                  {{ formatRelativeTime(doc.deleted_at) }}
                </time>
              </td>
              <td>
                <span
                  class="purge-badge"
                  :class="{ 'purge-warning': doc.days_until_purge <= 7 }"
                >
                  {{ formatPurgeDate(doc.purge_after, doc.days_until_purge) }}
                </span>
              </td>
              <td class="actions-cell">
                <button
                  @click="restoreDocument(doc)"
                  class="btn-restore btn-icon"
                  :disabled="restoring[doc.doc_id]"
                  title="Restore document to active"
                >
                  {{ restoring[doc.doc_id] ? '⏳' : '↩️' }}
                </button>
                <button
                  @click="confirmPermanentDelete(doc)"
                  class="btn-delete btn-icon btn-danger"
                  :disabled="deleting[doc.doc_id]"
                  title="Permanently delete document"
                >
                  {{ deleting[doc.doc_id] ? '⏳' : '🗑️' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Delete Confirmation Modal -->
      <div v-if="deleteConfirm.show" class="modal-overlay" @click.self="cancelDelete">
        <div class="modal modal-danger">
          <div class="modal-header">
            <h2>Permanently Delete Document?</h2>
            <button @click="cancelDelete" class="modal-close">×</button>
          </div>

          <div class="modal-body">
            <p class="warning-text">This will permanently delete the document. This action cannot be undone.</p>
            <p class="delete-details">
              <strong>{{ deleteConfirm.doc?.filename || 'Untitled' }}</strong><br />
              Namespace: {{ deleteConfirm.doc?.namespace || 'default' }}<br />
              Deleted: {{ formatRelativeTime(deleteConfirm.doc?.deleted_at) }}
            </p>
          </div>

          <div class="modal-footer">
            <button @click="cancelDelete" class="btn-secondary">Cancel</button>
            <button @click="permanentDelete" :disabled="deleting[deleteConfirm.doc?.doc_id]" class="btn-danger">
              {{ deleting[deleteConfirm.doc?.doc_id] ? 'Deleting...' : 'Delete Forever' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Empty Trash Confirmation Modal -->
      <div v-if="emptyTrashConfirm.show" class="modal-overlay" @click.self="cancelEmptyTrash">
        <div class="modal modal-danger">
          <div class="modal-header">
            <h2>Empty Trash?</h2>
            <button @click="cancelEmptyTrash" class="modal-close">×</button>
          </div>

          <div class="modal-body">
            <p class="warning-text">
              This will permanently delete {{ emptyTrashConfirm.count }} document{{ emptyTrashConfirm.count > 1 ? 's' : '' }}.
              This action cannot be undone.
            </p>
            <p v-if="selectedNamespace" class="delete-details">
              Deleting all documents in namespace: <strong>{{ selectedNamespace }}</strong>
            </p>
            <p v-else class="delete-details">
              Deleting all documents in trash
            </p>
          </div>

          <div class="modal-footer">
            <button @click="cancelEmptyTrash" class="btn-secondary">Cancel</button>
            <button @click="emptyTrash" :disabled="emptyingTrash" class="btn-danger">
              {{ emptyingTrash ? 'Deleting...' : 'Empty Trash' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { listTrash, restoreFromTrash, permanentlyDeleteFromTrash } from '../api/client.js'

const documents = ref([])
const loading = ref(false)
const error = ref(null)
const selectedNamespace = ref('')
const restoring = ref({})
const deleting = ref({})
const deleteConfirm = ref({
  show: false,
  doc: null,
})
const emptyTrashConfirm = ref({
  show: false,
  count: 0,
})
const emptyingTrash = ref(false)

onMounted(() => loadTrash())

async function loadTrash() {
  loading.value = true
  error.value = null

  try {
    const params = {}
    if (selectedNamespace.value && selectedNamespace.value !== '') {
      params.namespace = selectedNamespace.value
    }
    const response = await listTrash(params)
    documents.value = response.documents || []
  } catch (err) {
    error.value = err.message || 'Failed to load trash'
    console.error('Error loading trash:', err)
  } finally {
    loading.value = false
  }
}

const filteredDocuments = computed(() => {
  if (!selectedNamespace.value) {
    return documents.value
  }
  return documents.value.filter(doc => doc.namespace === selectedNamespace.value)
})

const uniqueNamespaces = computed(() => {
  const namespaces = new Set(documents.value.map(doc => doc.namespace))
  return Array.from(namespaces).sort()
})

async function restoreDocument(doc) {
  restoring.value[doc.doc_id] = true

  try {
    await restoreFromTrash({
      doc_id: doc.doc_id,
      namespace: doc.namespace,
      deleted_at_ms: doc.deleted_at_ms,
    })
    documents.value = documents.value.filter(
      d => !(d.doc_id === doc.doc_id && d.deleted_at_ms === doc.deleted_at_ms)
    )
  } catch (err) {
    error.value = err.message || 'Failed to restore document'
    console.error('Error restoring document:', err)
  } finally {
    delete restoring.value[doc.doc_id]
  }
}

function confirmPermanentDelete(doc) {
  deleteConfirm.value = { show: true, doc }
}

function cancelDelete() {
  deleteConfirm.value = { show: false, doc: null }
}

async function permanentDelete() {
  const doc = deleteConfirm.value.doc
  if (!doc) return

  deleteConfirm.value.show = false
  deleting.value[doc.doc_id] = true

  try {
    await permanentlyDeleteFromTrash({
      doc_id: doc.doc_id,
      namespace: doc.namespace,
      deleted_at_ms: doc.deleted_at_ms,
      filename: doc.filename,  // Pass trash entry filename for correct PK
    })
    documents.value = documents.value.filter(
      d => !(d.doc_id === doc.doc_id && d.deleted_at_ms === doc.deleted_at_ms)
    )
  } catch (err) {
    error.value = err.message || 'Failed to delete document'
    console.error('Error deleting document:', err)
  } finally {
    delete deleting.value[doc.doc_id]
  }
}

function formatRelativeTime(isoDate) {
  if (!isoDate) return 'Unknown'
  const date = new Date(isoDate)
  const now = new Date()
  const diffMs = now - date
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

  if (diffDays > 0) {
    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`
  }
  if (diffHours > 0) {
    return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`
  }
  if (diffMins > 0) {
    return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`
  }
  return 'Just now'
}

function formatPurgeDate(purgeAfter, daysUntil) {
  if (daysUntil <= 0) return 'Purging soon'
  if (daysUntil === 1) return 'Tomorrow'
  if (daysUntil <= 7) return `${daysUntil} days`
  if (!purgeAfter) return 'Unknown'
  const date = new Date(purgeAfter)
  return date.toLocaleDateString()
}

function confirmEmptyTrash() {
  emptyTrashConfirm.value = {
    show: true,
    count: filteredDocuments.value.length,
  }
}

function cancelEmptyTrash() {
  emptyTrashConfirm.value = { show: false, count: 0 }
}

async function emptyTrash() {
  emptyingTrash.value = true
  emptyTrashConfirm.value.show = false

  const docsToDelete = [...filteredDocuments.value]
  let deleted = 0
  let errors = []

  for (const doc of docsToDelete) {
    try {
      await permanentlyDeleteFromTrash({
        doc_id: doc.doc_id,
        namespace: doc.namespace,
        deleted_at_ms: doc.deleted_at_ms,
        filename: doc.filename,  // Pass trash entry filename for correct PK
      })
      documents.value = documents.value.filter(
        d => !(d.doc_id === doc.doc_id && d.deleted_at_ms === doc.deleted_at_ms)
      )
      deleted++
    } catch (err) {
      errors.push(`${doc.filename}: ${err.message}`)
      console.error('Error deleting document:', doc.doc_id, err)
    }
  }

  emptyingTrash.value = false

  if (errors.length > 0) {
    error.value = `Deleted ${deleted} documents. ${errors.length} failed: ${errors[0]}`
  }
}
</script>

<style scoped>
.trash-page {
  padding: 20px 0;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

.page-header {
  margin-bottom: 30px;
}

.page-header h1 {
  font-size: 2.5rem;
  margin: 0 0 10px 0;
  color: #1f2937;
}

.page-header .subtitle {
  color: #6b7280;
  margin: 0;
  font-size: 1rem;
}

.filters-bar {
  margin-bottom: 20px;
  padding: 15px;
  background: #f9fafb;
  border-radius: 8px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 15px;
}

.filter-actions {
  display: flex;
  gap: 10px;
}

.btn-empty-trash {
  padding: 8px 16px;
  background-color: #ef4444;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background-color 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-empty-trash:hover:not(:disabled) {
  background-color: #dc2626;
}

.btn-empty-trash:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-empty-trash .doc-count {
  opacity: 0.9;
}

.namespace-filter-wrapper {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.namespace-filter-wrapper label {
  font-weight: 500;
  color: #374151;
  font-size: 0.875rem;
}

.namespace-select {
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background-color: white;
  color: #1f2937;
  font-size: 0.875rem;
  cursor: pointer;
  transition: border-color 0.2s;
}

.namespace-select:hover {
  border-color: #9ca3af;
}

.namespace-select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.loading-state,
.error-state,
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #6b7280;
}

.loading-state p {
  font-size: 1.125rem;
}

.error-state {
  padding: 40px 20px;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  border-radius: 8px;
  color: #991b1b;
}

.error-message {
  margin-bottom: 20px;
  font-weight: 500;
}

.empty-state p:first-child {
  font-size: 1.25rem;
  font-weight: 500;
  margin-bottom: 10px;
}

.empty-state .hint {
  font-size: 0.875rem;
  color: #9ca3af;
}

.trash-table-container {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #d1d5db;
}

.trash-table {
  width: 100%;
  border-collapse: collapse;
  background: white;
}

.trash-table thead {
  background-color: #f3f4f6;
  border-bottom: 2px solid #d1d5db;
}

.trash-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: #374151;
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.trash-table tbody tr {
  border-bottom: 1px solid #e5e7eb;
  transition: background-color 0.15s;
}

.trash-table tbody tr:hover {
  background-color: #f9fafb;
}

.trash-table td {
  padding: 12px 16px;
  color: #1f2937;
  font-size: 0.875rem;
}

.filename-cell {
  font-weight: 500;
}

.filename {
  word-break: break-word;
}

.namespace-badge {
  display: inline-block;
  padding: 4px 12px;
  background-color: #dbeafe;
  color: #1e40af;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 500;
}

.deleted-date {
  color: #6b7280;
  font-size: 0.875rem;
}

.deleted-date time {
  display: block;
}

.purge-badge {
  display: inline-block;
  padding: 4px 12px;
  background-color: #fef3c7;
  color: #854d0e;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 500;
}

.purge-warning {
  background-color: #fee2e2;
  color: #991b1b;
}

.actions-cell {
  display: flex;
  gap: 8px;
}

.btn-icon {
  padding: 6px 10px;
  font-size: 1rem;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.btn-restore {
  color: #10b981;
}

.btn-restore:hover:not(:disabled) {
  background-color: #d1fae5;
}

.btn-delete {
  color: #ef4444;
}

.btn-danger:hover:not(:disabled) {
  background-color: #fee2e2;
}

.btn-icon:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary,
.btn-secondary {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  font-size: 0.875rem;
  transition: all 0.2s;
}

.btn-primary {
  background-color: #3b82f6;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background-color: #2563eb;
}

.btn-secondary {
  background-color: #e5e7eb;
  color: #1f2937;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #d1d5db;
}

.btn-danger {
  background-color: #ef4444;
  color: white;
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-danger:hover:not(:disabled) {
  background-color: #dc2626;
}

.btn-primary:disabled,
.btn-secondary:disabled,
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: white;
  border-radius: 8px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  max-width: 500px;
  width: 90%;
}

.modal-danger {
  border-left: 4px solid #ef4444;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  margin: 0;
  font-size: 1.25rem;
  color: #1f2937;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #6b7280;
  transition: color 0.2s;
}

.modal-close:hover {
  color: #1f2937;
}

.modal-body {
  padding: 20px;
}

.modal-body p {
  margin: 0 0 15px 0;
  color: #4b5563;
  line-height: 1.6;
}

.warning-text {
  color: #991b1b;
  font-weight: 500;
  padding: 12px;
  background-color: #fef2f2;
  border-left: 4px solid #ef4444;
  border-radius: 4px;
}

.delete-details {
  background-color: #f3f4f6;
  padding: 12px;
  border-radius: 4px;
  font-size: 0.875rem;
  color: #1f2937;
  line-height: 1.6;
}

.delete-details strong {
  display: block;
  margin-bottom: 4px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 20px;
  border-top: 1px solid #e5e7eb;
  background-color: #f9fafb;
}

/* Responsive Design */
@media (max-width: 768px) {
  .page-header h1 {
    font-size: 1.75rem;
  }

  .filters-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .namespace-filter-wrapper {
    width: 100%;
  }

  .namespace-select {
    width: 100%;
  }

  .filter-actions {
    width: 100%;
  }

  .btn-empty-trash {
    width: 100%;
    justify-content: center;
  }

  .trash-table {
    font-size: 0.75rem;
  }

  .trash-table th,
  .trash-table td {
    padding: 8px 12px;
  }

  .actions-cell {
    flex-direction: column;
    gap: 4px;
  }

  .btn-icon {
    width: 100%;
    text-align: center;
  }

  .modal {
    width: 95%;
  }
}

@media (max-width: 480px) {
  .container {
    padding: 0 10px;
  }

  .page-header h1 {
    font-size: 1.5rem;
  }

  .trash-table th,
  .trash-table td {
    padding: 6px 8px;
    font-size: 0.7rem;
  }

  .modal-header h2 {
    font-size: 1.1rem;
  }
}
</style>
