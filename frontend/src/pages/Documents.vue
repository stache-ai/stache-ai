<template>
  <div class="documents-page">
    <div class="container">
      <div class="page-header">
        <h1>📄 Documents</h1>
        <p class="subtitle">Browse and manage your knowledge base</p>
      </div>

      <!-- Filters and Search -->
      <div class="filters-bar">
        <div class="search-box">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search documents by filename..."
            class="search-input"
            @input="debouncedSearch"
          />
        </div>

        <div class="filter-controls">
          <div class="namespace-filter-wrapper">
            <NamespaceTreeDropdown
              v-model="selectedNamespace"
              :tree="namespaceTree"
              :flat-namespaces="namespaces"
              :allow-empty="true"
              empty-label="All Namespaces"
              @update:modelValue="() => loadDocuments()"
            />
          </div>

          <button @click="loadDocuments" class="btn-secondary" :disabled="loading">
            🔄 Refresh
          </button>
        </div>
      </div>

      <!-- Document Table -->
      <div v-if="loading && documents.length === 0" class="loading-state">
        <p>Loading documents...</p>
      </div>

      <div v-else-if="error" class="error-state">
        <p class="error-message">{{ error }}</p>
        <button @click="loadDocuments" class="btn-primary">Retry</button>
      </div>

      <div v-else-if="documents.length === 0" class="empty-state">
        <p>No documents found</p>
        <p class="hint">Upload documents via the Capture page or CLI</p>
      </div>

      <!-- Bulk Action Bar -->
      <div v-if="selectedDocs.length > 0" class="bulk-action-bar">
        <div class="selection-info">
          <span class="selection-count">{{ selectedDocs.length }} selected</span>
          <button @click="clearSelection" class="btn-link">Clear</button>
        </div>
        <div class="bulk-actions">
          <button type="button" @click="confirmBulkDelete" class="btn-bulk-delete" :disabled="bulkDeleting">
            🗑️ Delete Selected
          </button>
        </div>
      </div>

      <div class="documents-table-container">
        <table class="documents-table">
          <thead>
            <tr>
              <th class="checkbox-cell">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  :indeterminate="isPartiallySelected"
                  @change="toggleSelectAll"
                  class="checkbox"
                />
              </th>
              <th>Filename</th>
              <th>Namespace</th>
              <th>Chunks</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in filteredDocuments" :key="doc.doc_id" :class="{ selected: isSelected(doc) }">
              <td class="checkbox-cell">
                <input
                  type="checkbox"
                  :checked="isSelected(doc)"
                  @change="toggleSelect(doc)"
                  class="checkbox"
                />
              </td>
              <td class="filename-cell">
                <span class="filename">{{ doc.filename || 'Untitled' }}</span>
                <span v-if="doc.metadata && Object.keys(doc.metadata).length > 0" class="has-metadata" title="Has custom metadata">🏷️</span>
              </td>
              <td>
                <span class="namespace-badge">{{ doc.namespace || 'default' }}</span>
              </td>
              <td class="chunk-count">{{ doc.chunk_count || 0 }}</td>
              <td class="created-date">{{ formatDate(doc.created_at) }}</td>
              <td class="actions-cell">
                <button @click="editDocument(doc)" class="btn-icon" title="Edit metadata">
                  ✏️
                </button>
                <button @click="confirmDelete(doc)" class="btn-icon btn-danger" title="Delete document">
                  🗑️
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Pagination -->
        <div v-if="hasMoreDocuments" class="pagination">
          <button @click="loadMoreDocuments" :disabled="loading" class="btn-secondary">
            {{ loading ? 'Loading...' : 'Load More' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Document Modal -->
    <div v-if="editingDoc" class="modal-overlay" @click.self="cancelEdit">
      <div class="modal">
        <div class="modal-header">
          <h2>Edit Document Metadata</h2>
          <button @click="cancelEdit" class="modal-close">×</button>
        </div>

        <div class="modal-body">
          <!-- Summary Section (read-only) -->
          <div class="summary-section">
            <label>Summary</label>
            <div v-if="editForm.loadingSummary" class="summary-loading">
              Loading summary...
            </div>
            <div v-else-if="editForm.summary" class="summary-content">
              <p class="summary-text">{{ editForm.summary }}</p>
            </div>
            <div v-else class="summary-empty">
              No summary available
            </div>
            <div v-if="editForm.headings?.length > 0" class="headings-list">
              <span class="headings-label">Headings:</span>
              <span v-for="heading in editForm.headings.slice(0, 10)" :key="heading" class="heading-tag">{{ heading }}</span>
              <span v-if="editForm.headings.length > 10" class="more-headings">+{{ editForm.headings.length - 10 }} more</span>
            </div>
          </div>

          <div class="form-group">
            <label>Filename</label>
            <input v-model="editForm.filename" type="text" class="form-input" />
          </div>

          <div class="form-group">
            <label>Namespace</label>
            <NamespaceTreeDropdown
              v-model="editForm.namespace"
              :tree="namespaceTree"
              :flat-namespaces="namespaces"
              :allow-empty="true"
              empty-label="default"
            />
          </div>

          <div class="form-group">
            <label>Custom Metadata (JSON)</label>
            <textarea
              v-model="editForm.metadataJson"
              class="form-textarea"
              rows="6"
              placeholder='{"key": "value"}'
            ></textarea>
            <p v-if="metadataError" class="field-error">{{ metadataError }}</p>
          </div>
        </div>

        <div class="modal-footer">
          <button @click="cancelEdit" class="btn-secondary">Cancel</button>
          <button @click="saveDocument" :disabled="saving || metadataError" class="btn-primary">
            {{ saving ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="deletingDoc" class="modal-overlay" @click.self="cancelDelete">
      <div class="modal modal-danger">
        <div class="modal-header">
          <h2>Delete Document</h2>
          <button @click="cancelDelete" class="modal-close">×</button>
        </div>

        <div class="modal-body">
          <p>Are you sure you want to delete this document?</p>
          <p class="delete-details">
            <strong>{{ deletingDoc.filename || 'Untitled' }}</strong><br />
            Namespace: {{ deletingDoc.namespace || 'default' }}<br />
            Chunks: {{ deletingDoc.chunk_count || 0 }}
          </p>
          <p class="warning">This action cannot be undone.</p>
        </div>

        <div class="modal-footer">
          <button @click="cancelDelete" class="btn-secondary">Cancel</button>
          <button @click="deleteDocument" :disabled="deleting" class="btn-danger">
            {{ deleting ? 'Deleting...' : 'Delete Document' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Bulk Delete Confirmation Modal -->
    <div v-if="bulkDeleteConfirm.show" class="modal-overlay" @click.self="cancelBulkDelete">
      <div class="modal modal-danger">
        <div class="modal-header">
          <h2>Delete {{ bulkDeleteConfirm.count }} Documents?</h2>
          <button @click="cancelBulkDelete" class="modal-close">×</button>
        </div>

        <div class="modal-body">
          <p class="warning">This will move {{ bulkDeleteConfirm.count }} document{{ bulkDeleteConfirm.count > 1 ? 's' : '' }} to trash.</p>
          <p>Documents can be restored within 30 days.</p>
        </div>

        <div class="modal-footer">
          <button @click="cancelBulkDelete" class="btn-secondary">Cancel</button>
          <button @click="bulkDelete" :disabled="bulkDeleting" class="btn-danger">
            {{ bulkDeleting ? 'Deleting...' : 'Delete Selected' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { listDocuments, getDocumentById, updateDocumentMetadata, deleteDocumentById, listNamespaces, getNamespaceTree } from '../api/client.js'
import NamespaceTreeDropdown from '../components/NamespaceTreeDropdown.vue'

const documents = ref([])
const namespaces = ref([])
const namespaceTree = ref([])
const loading = ref(false)
const error = ref(null)
const searchQuery = ref('')
const selectedNamespace = ref('')
const limit = ref(50)
const nextKey = ref(null)
const hasMoreDocuments = ref(false)

// Edit state
const editingDoc = ref(null)
const editForm = ref({
  filename: '',
  namespace: '',
  metadataJson: ''
})
const saving = ref(false)
const metadataError = ref(null)

// Delete state
const deletingDoc = ref(null)
const deleting = ref(false)

// Selection state
const selectedDocs = ref([])
const bulkDeleting = ref(false)
const bulkDeleteConfirm = ref({
  show: false,
  count: 0,
})

// Load documents
const loadDocuments = async (append = false) => {
  loading.value = true
  error.value = null

  try {
    // Reset pagination and selection if not appending (new filter or refresh)
    if (!append) {
      nextKey.value = null
      selectedDocs.value = []
    }

    const params = {
      limit: limit.value
    }
    // Only add namespace param if a specific namespace is selected
    if (selectedNamespace.value && selectedNamespace.value !== '') {
      params.namespace = selectedNamespace.value
    }
    // Add pagination token if loading more
    if (append && nextKey.value) {
      params.next_key = nextKey.value
    }

    const response = await listDocuments(params)

    if (append) {
      documents.value.push(...response.documents)
    } else {
      documents.value = response.documents || []
    }

    // Store pagination token for next page
    nextKey.value = response.next_key || null
    hasMoreDocuments.value = !!response.next_key
  } catch (err) {
    error.value = err.message || 'Failed to load documents'
    console.error('Error loading documents:', err)
  } finally {
    loading.value = false
  }
}

const loadMoreDocuments = async () => {
  await loadDocuments(true)
}

// Load namespaces for filter
const loadNamespaces = async () => {
  try {
    const [listResponse, treeResponse] = await Promise.all([
      listNamespaces(false),
      getNamespaceTree(true)
    ])
    namespaces.value = listResponse.namespaces || []
    namespaceTree.value = treeResponse.tree || []
  } catch (err) {
    console.error('Error loading namespaces:', err)
  }
}

// Search and filter
const filteredDocuments = computed(() => {
  if (!searchQuery.value.trim()) {
    return documents.value
  }

  const query = searchQuery.value.toLowerCase()
  return documents.value.filter(doc => {
    const filename = (doc.filename || '').toLowerCase()
    return filename.includes(query)
  })
})

// Debounced search (client-side for now)
let searchTimeout = null
const debouncedSearch = () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    // Could implement server-side search here
  }, 300)
}

// Edit document
const editDocument = async (doc) => {
  editingDoc.value = doc
  editForm.value = {
    filename: doc.filename || '',
    namespace: doc.namespace || '',
    metadataJson: doc.metadata ? JSON.stringify(doc.metadata, null, 2) : '',
    summary: null,
    headings: [],
    loadingSummary: true
  }
  metadataError.value = null

  // Fetch full details including summary
  try {
    const details = await getDocumentById(doc.doc_id, doc.namespace || 'default')
    // Check summary at top-level first, then fall back to metadata.ai_summary
    editForm.value.summary = details.summary || details.metadata?.ai_summary || null
    editForm.value.headings = details.headings || []
  } catch (err) {
    console.error('Error fetching document details:', err)
  } finally {
    editForm.value.loadingSummary = false
  }
}

const cancelEdit = () => {
  editingDoc.value = null
  editForm.value = { filename: '', namespace: '', metadataJson: '' }
  metadataError.value = null
}

// Validate metadata JSON
watch(() => editForm.value.metadataJson, (newValue) => {
  if (!newValue.trim()) {
    metadataError.value = null
    return
  }

  try {
    JSON.parse(newValue)
    metadataError.value = null
  } catch (err) {
    metadataError.value = 'Invalid JSON'
  }
})

const saveDocument = async () => {
  if (metadataError.value) return

  saving.value = true
  try {
    const updates = {}

    if (editForm.value.filename !== editingDoc.value.filename) {
      updates.filename = editForm.value.filename
    }

    if (editForm.value.namespace !== editingDoc.value.namespace) {
      updates.namespace = editForm.value.namespace || 'default'
    }

    if (editForm.value.metadataJson.trim()) {
      const parsedMetadata = JSON.parse(editForm.value.metadataJson)
      updates.metadata = parsedMetadata
    } else if (editingDoc.value.metadata) {
      // Clear metadata if it was removed
      updates.metadata = {}
    }

    await updateDocumentMetadata(
      editingDoc.value.doc_id,
      editingDoc.value.namespace || 'default',
      updates
    )

    // Refresh documents list
    await loadDocuments()
    cancelEdit()
  } catch (err) {
    error.value = err.message || 'Failed to update document'
    console.error('Error updating document:', err)
  } finally {
    saving.value = false
  }
}

// Delete document
const confirmDelete = (doc) => {
  deletingDoc.value = doc
}

const cancelDelete = () => {
  deletingDoc.value = null
}

const deleteDocument = async () => {
  deleting.value = true
  try {
    await deleteDocumentById(
      deletingDoc.value.doc_id,
      deletingDoc.value.namespace || 'default'
    )

    // Remove from local list
    documents.value = documents.value.filter(d => d.doc_id !== deletingDoc.value.doc_id)
    cancelDelete()
  } catch (err) {
    error.value = err.message || 'Failed to delete document'
    console.error('Error deleting document:', err)
  } finally {
    deleting.value = false
  }
}

// Selection functions
const isSelected = (doc) => selectedDocs.value.some(d => d.doc_id === doc.doc_id)

const toggleSelect = (doc) => {
  if (isSelected(doc)) {
    selectedDocs.value = selectedDocs.value.filter(d => d.doc_id !== doc.doc_id)
  } else {
    selectedDocs.value.push(doc)
  }
}

const toggleSelectAll = () => {
  if (isAllSelected.value) {
    selectedDocs.value = []
  } else {
    selectedDocs.value = [...filteredDocuments.value]
  }
}

const clearSelection = () => {
  selectedDocs.value = []
}

const isAllSelected = computed(() => {
  return filteredDocuments.value.length > 0 && selectedDocs.value.length === filteredDocuments.value.length
})

const isPartiallySelected = computed(() => {
  return selectedDocs.value.length > 0 && selectedDocs.value.length < filteredDocuments.value.length
})

// Bulk delete
const confirmBulkDelete = () => {
  bulkDeleteConfirm.value.show = true
  bulkDeleteConfirm.value.count = selectedDocs.value.length
}

const cancelBulkDelete = () => {
  bulkDeleteConfirm.value = { show: false, count: 0 }
}

const bulkDelete = async () => {
  bulkDeleting.value = true
  bulkDeleteConfirm.value.show = false

  const docsToDelete = [...selectedDocs.value]
  let deleted = 0
  let errors = []

  for (const doc of docsToDelete) {
    try {
      await deleteDocumentById(doc.doc_id, doc.namespace || 'default')
      documents.value = documents.value.filter(d => d.doc_id !== doc.doc_id)
      selectedDocs.value = selectedDocs.value.filter(d => d.doc_id !== doc.doc_id)
      deleted++
    } catch (err) {
      errors.push(`${doc.filename}: ${err.message}`)
      console.error('Error deleting document:', doc.doc_id, err)
    }
  }

  bulkDeleting.value = false

  if (errors.length > 0) {
    error.value = `Deleted ${deleted} documents. ${errors.length} failed: ${errors[0]}`
  }
}

// Date formatting
const formatDate = (dateString) => {
  if (!dateString) return 'N/A'

  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  } catch {
    return 'N/A'
  }
}

onMounted(async () => {
  // Load namespaces first so dropdown is populated
  await loadNamespaces()
  // Then load documents
  await loadDocuments()
})
</script>

<style scoped>
.documents-page {
  min-height: 80vh;
}

.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 2rem;
}

.page-header {
  margin-bottom: 2rem;
}

.page-header h1 {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
  color: #1f2937;
}

.subtitle {
  font-size: 1.1rem;
  color: #6b7280;
}

/* Filters Bar */
.filters-bar {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}

.search-box {
  flex: 1;
  min-width: 250px;
}

.search-input {
  width: 100%;
  padding: 0.75rem 1rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.2s;
}

.search-input:focus {
  outline: none;
  border-color: #667eea;
}

.filter-controls {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}

.namespace-filter-wrapper {
  min-width: 250px;
  flex-shrink: 0;
}

/* States */
.loading-state,
.error-state,
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
}

.error-message {
  color: #ef4444;
  margin-bottom: 1rem;
}

.hint {
  color: #6b7280;
  font-size: 0.9rem;
}

/* Bulk Action Bar */
.bulk-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 12px;
  margin-bottom: 1rem;
}

.selection-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.selection-count {
  font-weight: 600;
}

.btn-link {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  text-decoration: underline;
  font-size: 0.9rem;
}

.btn-link:hover {
  color: white;
}

.bulk-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.4rem 0.8rem;
  font-size: 0.875rem;
}

.btn-bulk-delete {
  padding: 0.5rem 1rem;
  background: white;
  color: #ef4444;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-bulk-delete:hover:not(:disabled) {
  background: #fee2e2;
}

.btn-bulk-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Documents Table */
.documents-table-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.documents-table {
  width: 100%;
  border-collapse: collapse;
}

.documents-table thead {
  background: #f9fafb;
  border-bottom: 2px solid #e5e7eb;
}

.documents-table th {
  padding: 1rem;
  text-align: left;
  font-weight: 600;
  color: #374151;
  font-size: 0.9rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.checkbox-cell {
  width: 40px;
  text-align: center;
}

.checkbox {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: #667eea;
}

.documents-table tbody tr.selected {
  background: #f0f4ff;
}

.documents-table td {
  padding: 1rem;
  border-bottom: 1px solid #f3f4f6;
}

.documents-table tbody tr:hover {
  background: #f9fafb;
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.filename {
  font-weight: 500;
  color: #1f2937;
}

.has-metadata {
  font-size: 0.85rem;
  opacity: 0.6;
}

.namespace-badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  background: #ede9fe;
  color: #6d28d9;
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 500;
}

.chunk-count {
  color: #6b7280;
}

.created-date {
  color: #9ca3af;
  font-size: 0.9rem;
}

.actions-cell {
  display: flex;
  gap: 0.5rem;
}

/* Pagination */
.pagination {
  padding: 1.5rem;
  text-align: center;
  border-top: 1px solid #e5e7eb;
}

/* Buttons */
.btn-primary,
.btn-secondary,
.btn-danger,
.btn-icon {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-secondary {
  background: #f3f4f6;
  color: #374151;
}

.btn-secondary:hover:not(:disabled) {
  background: #e5e7eb;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.btn-icon {
  background: transparent;
  padding: 0.25rem 0.5rem;
  font-size: 1.2rem;
}

.btn-icon:hover {
  background: #f3f4f6;
  border-radius: 4px;
}

.btn-icon.btn-danger:hover {
  background: #fee2e2;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal {
  background: white;
  border-radius: 12px;
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
}

.modal-danger {
  border: 2px solid #ef4444;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 1.5rem;
  color: #1f2937;
}

.modal-close {
  background: none;
  border: none;
  font-size: 2rem;
  color: #9ca3af;
  cursor: pointer;
  padding: 0;
  width: 2rem;
  height: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-close:hover {
  color: #374151;
}

.modal-body {
  padding: 1.5rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
  color: #374151;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 6px;
  font-size: 1rem;
  font-family: inherit;
}

.form-textarea {
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 0.9rem;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: #667eea;
}

.field-error {
  color: #ef4444;
  font-size: 0.85rem;
  margin-top: 0.25rem;
}

.delete-details {
  background: #fef2f2;
  padding: 1rem;
  border-radius: 6px;
  margin: 1rem 0;
  color: #991b1b;
}

.warning {
  color: #ef4444;
  font-weight: 500;
}

/* Summary section in modal */
.summary-section {
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.summary-section label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
  color: #374151;
}

.summary-loading {
  color: #9ca3af;
  font-style: italic;
}

.summary-content {
  background: #f9fafb;
  border-radius: 6px;
  padding: 1rem;
  max-height: 200px;
  overflow-y: auto;
}

.summary-text {
  margin: 0;
  color: #374151;
  font-size: 0.95rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.summary-empty {
  color: #9ca3af;
  font-style: italic;
}

.headings-list {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.headings-label {
  font-size: 0.85rem;
  color: #6b7280;
}

.heading-tag {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  background: #ede9fe;
  color: #6d28d9;
  border-radius: 4px;
  font-size: 0.8rem;
}

.more-headings {
  font-size: 0.8rem;
  color: #9ca3af;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 1.5rem;
  border-top: 1px solid #e5e7eb;
}

/* Mobile Responsive */
@media (max-width: 768px) {
  .page-header h1 {
    font-size: 2rem;
  }

  .filters-bar {
    flex-direction: column;
  }

  .filter-controls {
    flex-direction: column;
  }

  .documents-table {
    font-size: 0.85rem;
  }

  .documents-table th,
  .documents-table td {
    padding: 0.75rem 0.5rem;
  }

  .created-date {
    display: none;
  }
}
</style>
