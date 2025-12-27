<template>
  <div class="container">
    <!-- Loading State -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>Loading pending items...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="error-banner">
      <div class="error-icon">❌</div>
      <div>
        <strong>Failed to load pending items</strong>
        <p>{{ error }}</p>
      </div>
      <button @click="loadPending" class="btn-retry">Retry</button>
    </div>

    <!-- Empty State -->
    <div v-else-if="pendingItems.length === 0" class="empty-state">
      <div class="empty-icon">📭</div>
      <h2>No pending items</h2>
      <p>Documents from the dropbox will appear here for review</p>
    </div>

    <!-- Pending Items List -->
    <div v-else class="pending-list">
      <div v-for="item in pendingItems" :key="item.id" class="pending-card">
        <div class="card-thumbnail" @click="selectItem(item)">
          <img
            v-if="item.thumbnailUrl"
            :src="item.thumbnailUrl"
            :alt="item.original_filename"
            class="thumbnail-img"
          />
          <div v-else class="thumbnail-placeholder">📄</div>
        </div>

        <div class="card-content">
          <h3>{{ item.original_filename }}</h3>
          <div class="card-meta">
            <span class="meta-item">📅 {{ formatDate(item.created_at) }}</span>
            <span class="meta-item">📏 {{ formatTextLength(item.full_text_length) }}</span>
          </div>
          <div class="ai-suggestions">
            <div class="suggestion">
              <strong>Suggested name:</strong> {{ item.suggested_filename }}
            </div>
            <div class="suggestion">
              <strong>Suggested namespace:</strong> {{ item.suggested_namespace }}
            </div>
          </div>
          <div class="card-actions">
            <button @click="selectItem(item)" class="btn btn-primary">
              Review & Approve
            </button>
            <button @click="confirmDelete(item)" class="btn btn-danger">
              Reject
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Review Modal -->
    <div v-if="selectedItem" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-header">
          <h2>Review Document</h2>
          <button @click="closeModal" class="close-btn">×</button>
        </div>

        <div class="modal-body">
          <!-- PDF Preview -->
          <div class="pdf-preview">
            <iframe
              v-if="selectedItem.pdfUrl"
              :src="selectedItem.pdfUrl"
              class="pdf-frame"
              title="PDF Preview"
            ></iframe>
          </div>

          <!-- Review Form -->
          <div class="review-form">
            <div class="form-group">
              <label for="filename">Filename *</label>
              <input
                id="filename"
                v-model="reviewForm.filename"
                type="text"
                placeholder="document-name"
                required
              />
            </div>

            <div class="form-group">
              <label for="namespace">Namespace *</label>
              <input
                id="namespace"
                v-model="reviewForm.namespace"
                type="text"
                placeholder="e.g. work/projects"
                required
              />
            </div>

            <div class="form-group">
              <label>Chunking Strategy</label>
              <select v-model="reviewForm.chunkingStrategy">
                <option value="recursive">Recursive (recommended)</option>
                <option value="markdown">Markdown</option>
                <option value="semantic">Semantic</option>
                <option value="character">Character</option>
              </select>
            </div>

            <!-- Metadata Fields -->
            <MetadataFields ref="metadataRef" v-model="reviewForm.metadata" />

            <!-- Prepend Metadata -->
            <div class="form-group">
              <label>Prepend Metadata to Chunks (optional)</label>
              <input
                v-model="prependMetadataInput"
                type="text"
                placeholder="e.g. speaker, topic, date"
              />
              <div class="hint">
                Comma-separated list of metadata keys to embed in vector for better search
              </div>
            </div>

            <!-- Text Preview -->
            <div class="text-preview">
              <label>Extracted Text Preview</label>
              <div class="preview-content">
                {{ selectedItem.extracted_text }}
                <span v-if="selectedItem.full_text_length > selectedItem.extracted_text.length" class="more-text">
                  ... ({{ selectedItem.full_text_length - selectedItem.extracted_text.length }} more characters)
                </span>
              </div>
            </div>

            <!-- Actions -->
            <div class="modal-actions">
              <button
                @click="approveItem"
                :disabled="approving || !canApprove"
                class="btn btn-primary"
              >
                {{ approving ? 'Approving...' : 'Approve & Ingest' }}
              </button>
              <button @click="closeModal" class="btn btn-secondary">
                Cancel
              </button>
            </div>

            <!-- Result -->
            <div v-if="approveResult" class="result" :class="approveResult.type">
              <div class="result-icon">{{ approveResult.type === 'success' ? '✅' : '❌' }}</div>
              <div class="result-content">
                <strong>{{ approveResult.message }}</strong>
                <p v-if="approveResult.details">{{ approveResult.details }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation -->
    <div v-if="deleteConfirm" class="modal-overlay" @click.self="deleteConfirm = null">
      <div class="modal confirm-modal">
        <div class="modal-header">
          <h2>Confirm Rejection</h2>
          <button @click="deleteConfirm = null" class="close-btn">×</button>
        </div>
        <div class="modal-body">
          <p>Are you sure you want to reject this document?</p>
          <p class="confirm-filename">{{ deleteConfirm.original_filename }}</p>
          <p class="confirm-warning">This will permanently delete the document from the queue.</p>
        </div>
        <div class="modal-actions">
          <button
            @click="deleteItem"
            :disabled="deleting"
            class="btn btn-danger"
          >
            {{ deleting ? 'Deleting...' : 'Yes, Reject' }}
          </button>
          <button @click="deleteConfirm = null" class="btn btn-secondary">
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  listPending,
  getPendingThumbnailUrl,
  getPendingPdfUrl,
  approvePending,
  deletePending
} from '../api/client.js'
import MetadataFields from '../components/MetadataFields.vue'

const pendingItems = ref([])
const loading = ref(true)
const error = ref(null)
const selectedItem = ref(null)
const deleteConfirm = ref(null)
const approving = ref(false)
const deleting = ref(false)
const approveResult = ref(null)
const metadataRef = ref(null)
const prependMetadataInput = ref('')

const reviewForm = ref({
  filename: '',
  namespace: '',
  chunkingStrategy: 'recursive',
  metadata: null
})

const canApprove = computed(() => {
  return reviewForm.value.filename.trim() && reviewForm.value.namespace.trim()
})

const loadPending = async () => {
  loading.value = true
  error.value = null
  try {
    const items = await listPending()
    // Add URLs for thumbnails and PDFs
    pendingItems.value = items.map(item => ({
      ...item,
      thumbnailUrl: getPendingThumbnailUrl(item.id),
      pdfUrl: getPendingPdfUrl(item.id)
    }))
  } catch (err) {
    error.value = err.response?.data?.detail || err.message
  } finally {
    loading.value = false
  }
}

const selectItem = (item) => {
  selectedItem.value = item
  // Pre-fill form with AI suggestions
  reviewForm.value = {
    filename: item.suggested_filename,
    namespace: item.suggested_namespace,
    chunkingStrategy: 'recursive',
    metadata: null
  }
  prependMetadataInput.value = ''
  approveResult.value = null
}

const closeModal = () => {
  selectedItem.value = null
  approveResult.value = null
  if (metadataRef.value) {
    metadataRef.value.reset()
  }
}

const approveItem = async () => {
  if (!canApprove.value) return

  approving.value = true
  approveResult.value = null

  try {
    // Parse prepend metadata
    const prependMetadata = prependMetadataInput.value
      .split(',')
      .map(k => k.trim())
      .filter(k => k.length > 0)

    const result = await approvePending(selectedItem.value.id, {
      filename: reviewForm.value.filename,
      namespace: reviewForm.value.namespace,
      metadata: reviewForm.value.metadata,
      chunkingStrategy: reviewForm.value.chunkingStrategy,
      prependMetadata: prependMetadata.length > 0 ? prependMetadata : undefined
    })

    approveResult.value = {
      type: 'success',
      message: 'Document approved and ingested!',
      details: `Created ${result.chunks_created} chunk(s) | doc_id: ${result.doc_id}`
    }

    // Capture the ID before timeout (prevents race condition if modal closes early)
    const approvedItemId = selectedItem.value.id

    // Remove from list after 2 seconds
    setTimeout(() => {
      pendingItems.value = pendingItems.value.filter(i => i.id !== approvedItemId)
      closeModal()
    }, 2000)
  } catch (err) {
    approveResult.value = {
      type: 'error',
      message: 'Failed to approve document',
      details: err.response?.data?.detail || err.message
    }
  } finally {
    approving.value = false
  }
}

const confirmDelete = (item) => {
  deleteConfirm.value = item
}

const deleteItem = async () => {
  if (!deleteConfirm.value) return

  deleting.value = true
  try {
    await deletePending(deleteConfirm.value.id)
    // Remove from list
    pendingItems.value = pendingItems.value.filter(i => i.id !== deleteConfirm.value.id)
    deleteConfirm.value = null
  } catch (err) {
    error.value = err.response?.data?.detail || err.message
  } finally {
    deleting.value = false
  }
}

const formatDate = (isoString) => {
  const date = new Date(isoString)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const formatTextLength = (length) => {
  if (length < 1000) return `${length} chars`
  if (length < 1000000) return `${(length / 1000).toFixed(1)}k chars`
  return `${(length / 1000000).toFixed(1)}m chars`
}

onMounted(() => {
  loadPending()
})
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

/* Loading State */
.loading {
  text-align: center;
  padding: 3rem;
}

.spinner {
  width: 50px;
  height: 50px;
  border: 4px solid #e5e7eb;
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Error Banner */
.error-banner {
  background: #fee2e2;
  border: 1px solid #fca5a5;
  padding: 1.5rem;
  border-radius: 12px;
  display: flex;
  gap: 1rem;
  align-items: center;
}

.error-icon {
  font-size: 2rem;
}

.btn-retry {
  margin-left: auto;
  padding: 0.5rem 1rem;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

.btn-retry:hover {
  background: #dc2626;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state h2 {
  color: #374151;
  margin-bottom: 0.5rem;
}

.empty-state p {
  color: #6b7280;
}

/* Pending List */
.pending-list {
  display: grid;
  gap: 1.5rem;
}

.pending-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  display: flex;
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}

.pending-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 12px rgba(0,0,0,0.15);
}

.card-thumbnail {
  width: 200px;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}

.thumbnail-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumbnail-placeholder {
  font-size: 4rem;
}

.card-content {
  flex: 1;
  padding: 1.5rem;
}

.card-content h3 {
  font-size: 1.25rem;
  color: #1f2937;
  margin-bottom: 0.75rem;
}

.card-meta {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
  color: #6b7280;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.ai-suggestions {
  background: #f0f4ff;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.suggestion {
  margin-bottom: 0.5rem;
}

.suggestion:last-child {
  margin-bottom: 0;
}

.suggestion strong {
  color: #374151;
  margin-right: 0.5rem;
}

.card-actions {
  display: flex;
  gap: 1rem;
}

/* Buttons */
.btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 2rem;
}

.modal {
  background: white;
  border-radius: 12px;
  max-width: 1200px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.confirm-modal {
  max-width: 500px;
}

.modal-header {
  padding: 1.5rem;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h2 {
  font-size: 1.5rem;
  color: #1f2937;
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  font-size: 2rem;
  color: #9ca3af;
  cursor: pointer;
  padding: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  color: #374151;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  gap: 2rem;
  padding: 1.5rem;
}

.confirm-modal .modal-body {
  display: block;
  padding: 1.5rem;
}

.confirm-filename {
  font-weight: 600;
  color: #374151;
  margin: 1rem 0;
}

.confirm-warning {
  color: #ef4444;
  font-size: 0.875rem;
}

.pdf-preview {
  flex: 1;
  min-width: 400px;
}

.pdf-frame {
  width: 100%;
  height: 600px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.review-form {
  flex: 1;
  min-width: 400px;
}

.form-group {
  margin-bottom: 1.5rem;
}

label {
  display: block;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.5rem;
}

input[type="text"],
select {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.2s;
}

input[type="text"]:focus,
select:focus {
  outline: none;
  border-color: #667eea;
}

select {
  background: white;
}

.hint {
  margin-top: 0.5rem;
  font-size: 0.875rem;
  color: #9ca3af;
}

.text-preview {
  margin-bottom: 1.5rem;
}

.preview-content {
  background: #f9fafb;
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #374151;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: 'Courier New', monospace;
}

.more-text {
  color: #667eea;
  font-style: italic;
}

.modal-actions {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
}

.result {
  margin-top: 1.5rem;
  padding: 1rem;
  border-radius: 8px;
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.result.success {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
}

.result.error {
  background: #fee2e2;
  border: 1px solid #fca5a5;
}

.result-icon {
  font-size: 1.5rem;
}

.result-content strong {
  display: block;
  margin-bottom: 0.25rem;
  color: #1f2937;
}

.result-content p {
  color: #6b7280;
  font-size: 0.875rem;
  margin: 0;
}

@media (max-width: 1024px) {
  .modal-body {
    flex-direction: column;
  }

  .pdf-preview,
  .review-form {
    min-width: auto;
  }

  .card-thumbnail {
    width: 150px;
  }
}

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

  .pending-card {
    flex-direction: column;
  }

  .card-thumbnail {
    width: 100%;
    height: 180px;
  }

  .card-content {
    padding: 1rem;
  }

  .card-content h3 {
    font-size: 1.1rem;
  }

  .card-meta {
    flex-direction: column;
    gap: 0.5rem;
  }

  .ai-suggestions {
    padding: 0.75rem;
    font-size: 0.8rem;
  }

  .card-actions {
    flex-direction: column;
  }

  .card-actions .btn {
    width: 100%;
    min-height: 48px;
  }

  /* Modal improvements */
  .modal-overlay {
    padding: 0.5rem;
  }

  .modal {
    max-height: 95vh;
    border-radius: 8px;
  }

  .modal-header {
    padding: 1rem;
  }

  .modal-header h2 {
    font-size: 1.25rem;
  }

  .modal-body {
    padding: 1rem;
    gap: 1rem;
  }

  .pdf-preview {
    display: none; /* Hide PDF preview on mobile - too cramped */
  }

  .review-form {
    min-width: 100%;
  }

  .form-group {
    margin-bottom: 1rem;
  }

  label {
    font-size: 0.9rem;
    margin-bottom: 0.375rem;
  }

  input[type="text"],
  select {
    min-height: 48px;
    font-size: 16px; /* Prevents zoom on iOS */
  }

  .text-preview {
    margin-bottom: 1rem;
  }

  .preview-content {
    max-height: 150px;
    font-size: 0.8rem;
  }

  .modal-actions {
    flex-direction: column;
    gap: 0.75rem;
  }

  .modal-actions .btn {
    width: 100%;
    min-height: 48px;
  }

  .result {
    margin-top: 1rem;
    padding: 0.75rem;
  }

  /* Confirm modal */
  .confirm-modal .modal-body {
    padding: 1rem;
  }

  .confirm-filename {
    font-size: 0.9rem;
    word-break: break-all;
  }

  /* Error banner */
  .error-banner {
    flex-direction: column;
    text-align: center;
    gap: 0.75rem;
  }

  .btn-retry {
    margin-left: 0;
    width: 100%;
  }

  /* Empty state */
  .empty-state {
    padding: 3rem 1.5rem;
  }

  .empty-icon {
    font-size: 3rem;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .page-header h1 {
    font-size: 1.5rem;
  }

  .page-header p {
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
  }

  .card-thumbnail {
    height: 150px;
  }

  .thumbnail-placeholder {
    font-size: 3rem;
  }

  .pending-list {
    gap: 1rem;
  }

  .close-btn {
    width: 44px;
    height: 44px;
  }
}
</style>
