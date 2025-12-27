<template>
  <div class="container">
    <div class="namespaces-layout">
      <!-- Sidebar with tree -->
      <aside class="sidebar">
        <div class="sidebar-header">
          <h3>Namespace Tree</h3>
          <button @click="showCreateModal = true" class="btn-icon" title="Create namespace">
            +
          </button>
        </div>
        <div class="tree-container">
          <div v-if="loading" class="loading">Loading...</div>
          <div v-else-if="tree.length === 0" class="empty">
            <p>No namespaces yet</p>
            <button @click="showCreateModal = true" class="btn btn-primary btn-sm">
              Create First Namespace
            </button>
          </div>
          <NamespaceTreeNode
            v-else
            v-for="node in tree"
            :key="node.id"
            :node="node"
            :selected-id="selectedNamespace?.id"
            @select="selectNamespace"
          />
        </div>
      </aside>

      <!-- Main content -->
      <main class="main-panel">
        <!-- No selection state -->
        <div v-if="!selectedNamespace" class="empty-state">
          <div class="empty-icon">📂</div>
          <h2>Select a Namespace</h2>
          <p>Choose a namespace from the tree to view details and documents</p>
        </div>

        <!-- Namespace details -->
        <div v-else class="namespace-details">
          <!-- Breadcrumb -->
          <div class="breadcrumb">
            <span
              v-for="(ancestor, idx) in selectedNamespace.ancestors"
              :key="ancestor.id"
            >
              <a href="#" @click.prevent="selectNamespaceById(ancestor.id)">{{ ancestor.name }}</a>
              <span class="separator">/</span>
            </span>
            <span class="current">{{ selectedNamespace.name }}</span>
          </div>

          <!-- Header with actions -->
          <div class="details-header">
            <div class="header-info">
              <h2>{{ selectedNamespace.name }}</h2>
              <p v-if="selectedNamespace.description" class="description">
                {{ selectedNamespace.description }}
              </p>
              <p v-else class="description muted">No description</p>
            </div>
            <div class="header-actions">
              <button @click="editNamespace" class="btn btn-secondary">Edit</button>
              <button @click="confirmDelete" class="btn btn-danger">Delete</button>
            </div>
          </div>

          <!-- Stats -->
          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-value">{{ selectedNamespace.doc_count || 0 }}</div>
              <div class="stat-label">Documents</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ selectedNamespace.chunk_count || 0 }}</div>
              <div class="stat-label">Chunks</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ formatDate(selectedNamespace.created_at) }}</div>
              <div class="stat-label">Created</div>
            </div>
          </div>

          <!-- Documents list -->
          <div class="documents-section">
            <div class="section-header">
              <h3>Documents</h3>
              <button @click="refreshDocuments" class="btn-icon" title="Refresh">
                ↻
              </button>
            </div>
            <div v-if="documentsLoading" class="loading">Loading documents...</div>
            <div v-else-if="documents.length === 0" class="empty-docs">
              <p>No documents in this namespace</p>
            </div>
            <div v-else class="documents-list">
              <div
                v-for="doc in documents"
                :key="doc.doc_id"
                class="document-item"
              >
                <div class="doc-icon">📄</div>
                <div class="doc-info">
                  <div class="doc-name">{{ doc.filename || doc.doc_id }}</div>
                  <div class="doc-meta">
                    {{ doc.total_chunks || '?' }} chunks
                    <span v-if="doc.created_at"> · {{ formatDate(doc.created_at) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Metadata -->
          <div v-if="selectedNamespace.metadata && Object.keys(selectedNamespace.metadata).length > 0" class="metadata-section">
            <h3>Metadata</h3>
            <div class="metadata-grid">
              <div v-for="(value, key) in selectedNamespace.metadata" :key="key" class="metadata-item">
                <span class="meta-key">{{ key }}:</span>
                <span class="meta-value">{{ value }}</span>
              </div>
            </div>
          </div>

          <!-- Filter Keys -->
          <div v-if="selectedNamespace.filter_keys && selectedNamespace.filter_keys.length > 0" class="filter-keys-section">
            <h3>Filter Keys</h3>
            <div class="filter-keys-display">
              <span v-for="key in selectedNamespace.filter_keys" :key="key" class="filter-key-badge">
                {{ key }}
              </span>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showCreateModal || showEditModal" class="modal-overlay" @click.self="closeModals">
      <div class="modal">
        <div class="modal-header">
          <h3>{{ showEditModal ? 'Edit Namespace' : 'Create Namespace' }}</h3>
          <button @click="closeModals" class="btn-close">×</button>
        </div>
        <form @submit.prevent="showEditModal ? saveEdit() : createNamespace()">
          <div class="form-group">
            <label for="ns-id">ID (slug)</label>
            <input
              id="ns-id"
              v-model="form.id"
              type="text"
              placeholder="e.g., mba/finance or personal"
              :disabled="showEditModal"
              required
            />
            <div class="hint">Use slashes for hierarchy (e.g., work/projects/alpha)</div>
          </div>
          <div class="form-group">
            <label for="ns-name">Display Name</label>
            <input
              id="ns-name"
              v-model="form.name"
              type="text"
              placeholder="e.g., Finance"
              required
            />
          </div>
          <div class="form-group">
            <label for="ns-desc">Description</label>
            <textarea
              id="ns-desc"
              v-model="form.description"
              rows="3"
              placeholder="What belongs in this namespace?"
            ></textarea>
          </div>
          <div class="form-group">
            <label for="ns-parent">Parent Namespace</label>
            <select id="ns-parent" v-model="form.parent_id">
              <option value="">None (root level)</option>
              <option v-for="ns in flatNamespaces" :key="ns.id" :value="ns.id">
                {{ ns.path || ns.name }}
              </option>
            </select>
          </div>

          <!-- Filter Keys -->
          <div class="form-group">
            <label>Filter Keys</label>
            <div class="filter-keys-container">
              <div class="filter-keys-input">
                <input
                  v-model="filterKeysInput"
                  type="text"
                  placeholder="e.g., source, date, author"
                  @keyup.enter="addFilterKey"
                />
                <button type="button" @click="addFilterKey" class="btn btn-sm btn-secondary">
                  Add
                </button>
              </div>
              <div v-if="form.filter_keys.length > 0" class="filter-keys-list">
                <span
                  v-for="(key, index) in form.filter_keys"
                  :key="key"
                  class="filter-key-chip"
                >
                  {{ key }}
                  <button type="button" @click="removeFilterKey(index)" class="chip-remove">x</button>
                </span>
              </div>
              <div class="hint">
                Metadata keys users can filter on when searching (e.g., source, date, author)
              </div>
            </div>
          </div>

          <div class="modal-actions">
            <button type="button" @click="closeModals" class="btn btn-secondary">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="formLoading">
              {{ formLoading ? 'Saving...' : (showEditModal ? 'Save Changes' : 'Create') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteModal" class="modal-overlay" @click.self="showDeleteModal = false">
      <div class="modal modal-danger">
        <div class="modal-header">
          <h3>Delete Namespace</h3>
          <button @click="showDeleteModal = false" class="btn-close">×</button>
        </div>
        <div class="modal-body">
          <p>Are you sure you want to delete <strong>{{ selectedNamespace?.name }}</strong>?</p>
          <div class="delete-options">
            <label class="checkbox-label">
              <input type="checkbox" v-model="deleteOptions.cascade" />
              Also delete child namespaces
            </label>
            <label class="checkbox-label warning">
              <input type="checkbox" v-model="deleteOptions.deleteDocuments" />
              Also delete all documents from vector DB (cannot be undone!)
            </label>
          </div>
        </div>
        <div class="modal-actions">
          <button @click="showDeleteModal = false" class="btn btn-secondary">Cancel</button>
          <button @click="deleteNamespace" class="btn btn-danger" :disabled="formLoading">
            {{ formLoading ? 'Deleting...' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  listNamespaces,
  getNamespaceTree,
  getNamespace,
  createNamespaceApi,
  updateNamespace,
  deleteNamespaceApi,
  getNamespaceDocuments
} from '../api/client.js'
import NamespaceTreeNode from '../components/NamespaceTreeNode.vue'

// State
const loading = ref(true)
const tree = ref([])
const flatNamespaces = ref([])
const selectedNamespace = ref(null)
const documents = ref([])
const documentsLoading = ref(false)

// Modals
const showCreateModal = ref(false)
const showEditModal = ref(false)
const showDeleteModal = ref(false)
const formLoading = ref(false)

// Form
const form = ref({
  id: '',
  name: '',
  description: '',
  parent_id: '',
  filter_keys: []
})

// Delete options
const deleteOptions = ref({
  cascade: false,
  deleteDocuments: false
})

// Lifecycle
onMounted(async () => {
  await loadTree()
})

// Methods
const loadTree = async () => {
  loading.value = true
  try {
    const [treeResponse, listResponse] = await Promise.all([
      getNamespaceTree(true),
      listNamespaces(true)
    ])
    tree.value = treeResponse.tree
    flatNamespaces.value = listResponse.namespaces
  } catch (error) {
    console.error('Failed to load namespaces:', error)
  } finally {
    loading.value = false
  }
}

const selectNamespace = async (namespace) => {
  try {
    const details = await getNamespace(namespace.id)
    selectedNamespace.value = details
    await loadDocuments()
  } catch (error) {
    console.error('Failed to load namespace:', error)
  }
}

const selectNamespaceById = async (id) => {
  try {
    const details = await getNamespace(id)
    selectedNamespace.value = details
    await loadDocuments()
  } catch (error) {
    console.error('Failed to load namespace:', error)
  }
}

const loadDocuments = async () => {
  if (!selectedNamespace.value) return
  documentsLoading.value = true
  try {
    const response = await getNamespaceDocuments(selectedNamespace.value.id)
    documents.value = response.documents
  } catch (error) {
    console.error('Failed to load documents:', error)
    documents.value = []
  } finally {
    documentsLoading.value = false
  }
}

const refreshDocuments = () => loadDocuments()

const createNamespace = async () => {
  formLoading.value = true
  try {
    await createNamespaceApi({
      id: form.value.id,
      name: form.value.name,
      description: form.value.description,
      parent_id: form.value.parent_id || null,
      filter_keys: form.value.filter_keys.length > 0 ? form.value.filter_keys : null
    })
    closeModals()
    await loadTree()
  } catch (error) {
    alert('Failed to create namespace: ' + (error.response?.data?.detail || error.message))
  } finally {
    formLoading.value = false
  }
}

const editNamespace = () => {
  form.value = {
    id: selectedNamespace.value.id,
    name: selectedNamespace.value.name,
    description: selectedNamespace.value.description || '',
    parent_id: selectedNamespace.value.parent_id || '',
    filter_keys: selectedNamespace.value.filter_keys || []
  }
  showEditModal.value = true
}

const saveEdit = async () => {
  formLoading.value = true
  try {
    await updateNamespace(selectedNamespace.value.id, {
      name: form.value.name,
      description: form.value.description,
      parent_id: form.value.parent_id || null,
      filter_keys: form.value.filter_keys
    })
    closeModals()
    await loadTree()
    // Refresh selected namespace
    await selectNamespaceById(selectedNamespace.value.id)
  } catch (error) {
    alert('Failed to update namespace: ' + (error.response?.data?.detail || error.message))
  } finally {
    formLoading.value = false
  }
}

const confirmDelete = () => {
  deleteOptions.value = { cascade: false, deleteDocuments: false }
  showDeleteModal.value = true
}

const deleteNamespace = async () => {
  formLoading.value = true
  try {
    await deleteNamespaceApi(
      selectedNamespace.value.id,
      deleteOptions.value.cascade,
      deleteOptions.value.deleteDocuments
    )
    showDeleteModal.value = false
    selectedNamespace.value = null
    documents.value = []
    await loadTree()
  } catch (error) {
    alert('Failed to delete namespace: ' + (error.response?.data?.detail || error.message))
  } finally {
    formLoading.value = false
  }
}

const closeModals = () => {
  showCreateModal.value = false
  showEditModal.value = false
  form.value = { id: '', name: '', description: '', parent_id: '', filter_keys: [] }
  filterKeysInput.value = ''
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString()
}

const filterKeysInput = ref('')

const addFilterKey = () => {
  const key = filterKeysInput.value.trim()
  if (key && !form.value.filter_keys.includes(key)) {
    // Validate format: alphanumeric, underscore, hyphen
    if (/^[a-zA-Z0-9_-]+$/.test(key)) {
      form.value.filter_keys.push(key)
      filterKeysInput.value = ''
    } else {
      alert('Invalid key format. Use only letters, numbers, underscores, and hyphens.')
    }
  }
}

const removeFilterKey = (index) => {
  form.value.filter_keys.splice(index, 1)
}
</script>

<style scoped>
.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 2rem;
}

.page-header {
  text-align: center;
  margin-bottom: 2rem;
}

.page-header h1 {
  font-size: 2.5rem;
  color: #1f2937;
  margin-bottom: 0.5rem;
}

.page-header p {
  color: #6b7280;
  font-size: 1.1rem;
}

.namespaces-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 2rem;
  min-height: 600px;
}

/* Sidebar */
.sidebar {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.sidebar-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #374151;
}

.tree-container {
  padding: 0.5rem;
  max-height: 500px;
  overflow-y: auto;
}

/* Main panel */
.main-panel {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  padding: 2rem;
}

.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  color: #6b7280;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state h2 {
  color: #374151;
  margin-bottom: 0.5rem;
}

/* Breadcrumb */
.breadcrumb {
  font-size: 0.875rem;
  color: #6b7280;
  margin-bottom: 1rem;
}

.breadcrumb a {
  color: #667eea;
  text-decoration: none;
}

.breadcrumb a:hover {
  text-decoration: underline;
}

.breadcrumb .separator {
  margin: 0 0.5rem;
  color: #d1d5db;
}

.breadcrumb .current {
  color: #374151;
  font-weight: 500;
}

/* Details header */
.details-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.header-info h2 {
  margin: 0 0 0.5rem;
  font-size: 1.75rem;
  color: #1f2937;
}

.description {
  color: #6b7280;
  margin: 0;
}

.description.muted {
  font-style: italic;
  color: #9ca3af;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

/* Stats grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: #f9fafb;
  padding: 1rem;
  border-radius: 8px;
  text-align: center;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #667eea;
}

.stat-label {
  font-size: 0.875rem;
  color: #6b7280;
}

/* Documents section */
.documents-section {
  margin-bottom: 2rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #374151;
}

.documents-list {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.document-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e7eb;
}

.document-item:last-child {
  border-bottom: none;
}

.doc-icon {
  font-size: 1.5rem;
}

.doc-name {
  font-weight: 500;
  color: #374151;
}

.doc-meta {
  font-size: 0.75rem;
  color: #9ca3af;
}

.empty-docs {
  text-align: center;
  padding: 2rem;
  color: #9ca3af;
  background: #f9fafb;
  border-radius: 8px;
}

/* Metadata section */
.metadata-section h3 {
  font-size: 1.1rem;
  color: #374151;
  margin-bottom: 1rem;
}

.metadata-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.metadata-item {
  background: #f3f4f6;
  padding: 0.25rem 0.75rem;
  border-radius: 4px;
  font-size: 0.875rem;
}

.meta-key {
  color: #6b7280;
}

.meta-value {
  color: #374151;
  font-weight: 500;
}

/* Buttons */
.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.8rem;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
}

.btn-secondary {
  background: #e5e7eb;
  color: #374151;
}

.btn-secondary:hover {
  background: #d1d5db;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover {
  background: #dc2626;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: white;
  font-size: 1.1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: #f3f4f6;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 100%;
  max-width: 500px;
  box-shadow: 0 20px 40px rgba(0,0,0,0.2);
}

.modal-danger .modal-header {
  background: #fef2f2;
  border-bottom-color: #fecaca;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #9ca3af;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.btn-close:hover {
  color: #374151;
}

.modal form,
.modal-body {
  padding: 1.5rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 0 0 12px 12px;
}

/* Form elements */
.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  font-weight: 500;
  color: #374151;
  margin-bottom: 0.375rem;
  font-size: 0.875rem;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 0.9rem;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.form-group input:disabled {
  background: #f3f4f6;
  color: #9ca3af;
}

.hint {
  font-size: 0.75rem;
  color: #9ca3af;
  margin-top: 0.25rem;
}

/* Filter Keys */
.filter-keys-container {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.filter-keys-input {
  display: flex;
  gap: 0.5rem;
}

.filter-keys-input input {
  flex: 1;
}

.filter-keys-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.filter-key-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #e0e7ff;
  color: #3730a3;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
}

.chip-remove {
  background: none;
  border: none;
  color: #6366f1;
  cursor: pointer;
  padding: 0;
  font-size: 0.875rem;
  line-height: 1;
}

.chip-remove:hover {
  color: #4338ca;
}

.filter-keys-section {
  margin-top: 1.5rem;
}

.filter-keys-section h3 {
  font-size: 1.1rem;
  color: #374151;
  margin-bottom: 0.75rem;
}

.filter-keys-display {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.filter-key-badge {
  background: #dbeafe;
  color: #1e40af;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.875rem;
  font-weight: 500;
}

/* Delete options */
.delete-options {
  margin-top: 1rem;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
}

.checkbox-label:hover {
  background: #f3f4f6;
}

.checkbox-label.warning {
  color: #dc2626;
}

/* Loading & Empty states */
.loading {
  text-align: center;
  padding: 2rem;
  color: #9ca3af;
}

.empty {
  text-align: center;
  padding: 2rem;
  color: #9ca3af;
}

.empty p {
  margin-bottom: 1rem;
}

/* Tablet breakpoint */
@media (max-width: 900px) {
  .namespaces-layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    max-height: 300px;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }
}

/* Mobile breakpoint */
@media (max-width: 768px) {
  .container {
    padding: 0 1rem;
  }

  .page-header {
    text-align: center;
  }

  .page-header h1 {
    font-size: 1.75rem;
  }

  .page-header p {
    font-size: 1rem;
  }

  .namespaces-layout {
    gap: 1rem;
    min-height: auto;
  }

  .sidebar {
    max-height: 250px;
  }

  .sidebar-header {
    padding: 0.75rem;
  }

  .tree-container {
    padding: 0.25rem;
    max-height: 200px;
  }

  .main-panel {
    padding: 1.25rem;
  }

  .empty-state {
    padding: 2rem 1rem;
  }

  .empty-icon {
    font-size: 3rem;
  }

  .details-header {
    flex-direction: column;
    gap: 1rem;
    align-items: stretch;
  }

  .header-info h2 {
    font-size: 1.5rem;
  }

  .header-actions {
    flex-wrap: wrap;
  }

  .header-actions .btn {
    flex: 1;
    min-width: 100px;
    text-align: center;
    min-height: 44px;
  }

  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
  }

  .stat-card {
    padding: 0.75rem 0.5rem;
  }

  .stat-value {
    font-size: 1.1rem;
  }

  .stat-label {
    font-size: 0.75rem;
  }

  .section-header h3 {
    font-size: 1rem;
  }

  .document-item {
    padding: 0.5rem 0.75rem;
  }

  .doc-icon {
    font-size: 1.25rem;
  }

  .doc-name {
    font-size: 0.9rem;
  }

  /* Modal improvements */
  .modal-overlay {
    padding: 1rem;
  }

  .modal {
    max-width: 100%;
    max-height: 90vh;
  }

  .modal-header {
    padding: 1rem;
  }

  .modal form,
  .modal-body {
    padding: 1rem;
  }

  .modal-actions {
    padding: 1rem;
    flex-wrap: wrap;
  }

  .modal-actions .btn {
    flex: 1;
    min-width: 100px;
    min-height: 44px;
  }

  .form-group input,
  .form-group select,
  .form-group textarea {
    min-height: 44px;
    font-size: 16px; /* Prevents zoom on iOS */
  }

  .checkbox-label {
    min-height: 44px;
  }

  .btn-icon {
    width: 36px;
    height: 36px;
    font-size: 1.2rem;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .page-header h1 {
    font-size: 1.5rem;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .stat-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
  }

  .stat-value {
    order: 2;
  }

  .stat-label {
    order: 1;
  }

  .header-actions {
    flex-direction: column;
  }

  .header-actions .btn {
    width: 100%;
  }
}
</style>
