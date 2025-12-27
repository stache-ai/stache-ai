<template>
  <div class="container">
    <div class="capture-form">
      <!-- Text Input -->
      <div class="form-group">
        <label for="thought">Text</label>
        <textarea
          id="thought"
          v-model="text"
          placeholder="Enter your thought, note, or idea here..."
          rows="6"
          @keydown.meta.enter="handleSubmit"
          @keydown.ctrl.enter="handleSubmit"
        ></textarea>
        <div class="hint">Tip: Press Cmd/Ctrl + Enter to save</div>
      </div>

      <!-- File Upload (Optional) - Now supports multiple files -->
      <div class="form-group">
        <label>Or Upload Files (optional)</label>
        <div
          class="dropzone"
          :class="{ 'drag-over': dragOver, 'has-file': files.length > 0 }"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="handleDrop"
          @click="$refs.fileInput.click()"
        >
          <input
            ref="fileInput"
            type="file"
            multiple
            accept=".txt,.md,.pdf,.epub,.docx,.pptx,.vtt,.srt"
            @change="handleFileSelect"
            style="display: none"
          />
          <div v-if="files.length > 0" class="files-preview">
            <div v-for="(file, index) in files" :key="index" class="file-preview">
              <span class="file-icon">📄</span>
              <span class="file-name">{{ file.name }}</span>
              <button type="button" @click.stop="removeFile(index)" class="file-clear">×</button>
            </div>
            <div v-if="files.length > 1" class="files-summary">
              {{ files.length }} files selected
            </div>
          </div>
          <div v-else class="dropzone-content">
            <p>Click or drag files here</p>
            <p class="dropzone-hint">TXT, MD, PDF, EPUB, DOCX, PPTX, VTT, SRT (multiple files supported)</p>
          </div>
        </div>
      </div>

      <!-- Namespace -->
      <div class="form-group">
        <NamespaceSelector
          v-model="namespace"
          label="Namespace (optional)"
          placeholder="Select or create namespace..."
          :allow-clear="true"
        />
      </div>

      <!-- Chunking Strategy (only shown for files) -->
      <div v-if="files.length > 0" class="form-group">
        <label>Chunking Strategy</label>
        <select v-model="chunkingStrategy">
          <option value="recursive">Recursive (recommended)</option>
          <option value="markdown">Markdown (for .md files)</option>
          <option value="transcript">Transcript (for .vtt/.srt files)</option>
          <option value="semantic">Semantic (preserves paragraphs)</option>
        </select>
      </div>

      <!-- Metadata (tags + custom attributes) -->
      <MetadataFields ref="metadataRef" v-model="metadata" />

      <!-- Actions -->
      <div class="form-actions">
        <button
          @click="handleSubmit"
          :disabled="!canSubmit || loading"
          class="btn btn-primary"
        >
          {{ loading ? (files.length > 1 ? `Uploading ${files.length} files...` : 'Saving...') : 'Save' }}
        </button>
        <button @click="clearForm" class="btn btn-secondary" :disabled="loading">Clear</button>
      </div>

      <!-- Upload Progress (for batch uploads) -->
      <div v-if="loading && uploadProgress > 0" class="progress-bar">
        <div class="progress-bar-fill" :style="{ width: uploadProgress + '%' }"></div>
      </div>

      <!-- Result -->
      <div v-if="result" class="result" :class="result.type">
        <div class="result-icon">{{ result.type === 'success' ? '✅' : result.type === 'warning' ? '⚠️' : '❌' }}</div>
        <div class="result-content">
          <strong>{{ result.message }}</strong>
          <p v-if="result.details">{{ result.details }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { captureThought, uploadDocument, batchUploadDocuments } from '../api/client.js'
import MetadataFields from '../components/MetadataFields.vue'
import NamespaceSelector from '../components/NamespaceSelector.vue'

const text = ref('')
const files = ref([])
const namespace = ref('')
const chunkingStrategy = ref('recursive')
const metadata = ref(null)
const metadataRef = ref(null)
const loading = ref(false)
const uploadProgress = ref(0)
const result = ref(null)
const dragOver = ref(false)
const fileInput = ref(null)

const canSubmit = computed(() => text.value.trim() || files.value.length > 0)

const handleFileSelect = (event) => {
  const selected = Array.from(event.target.files)
  if (selected.length > 0) {
    files.value = [...files.value, ...selected]
  }
}

const handleDrop = (event) => {
  dragOver.value = false
  const dropped = Array.from(event.dataTransfer.files)
  if (dropped.length > 0) {
    files.value = [...files.value, ...dropped]
  }
}

const removeFile = (index) => {
  files.value = files.value.filter((_, i) => i !== index)
}

const clearFiles = () => {
  files.value = []
  if (fileInput.value) fileInput.value.value = ''
}

const handleSubmit = async () => {
  if (!canSubmit.value) return

  loading.value = true
  uploadProgress.value = 0
  result.value = null

  const ns = namespace.value.trim() || null

  try {
    let response

    if (files.value.length > 1) {
      // Batch upload multiple files
      response = await batchUploadDocuments(files.value, {
        chunkingStrategy: chunkingStrategy.value,
        namespace: ns,
        skipErrors: true,
        onProgress: (percent) => {
          uploadProgress.value = percent
        }
      })
      result.value = {
        type: response.success ? 'success' : 'warning',
        message: response.message,
        details: `${response.successful} succeeded, ${response.failed} failed, ${response.total_chunks} total chunks`
      }
    } else if (files.value.length === 1) {
      // Single file upload
      response = await uploadDocument(files.value[0], chunkingStrategy.value, metadata.value, ns)
      result.value = {
        type: 'success',
        message: 'File uploaded successfully!',
        details: `Created ${response.chunks_created} chunk(s) from ${files.value[0].name}`
      }
    } else {
      // Capture text
      response = await captureThought(text.value, metadata.value, ns)
      result.value = {
        type: 'success',
        message: 'Captured successfully!',
        details: `Created ${response.chunks_created} chunk(s)`
      }
    }

    // Clear form after success
    setTimeout(clearForm, 3000)
  } catch (error) {
    result.value = {
      type: 'error',
      message: 'Failed to save',
      details: error.response?.data?.detail || error.message
    }
  } finally {
    loading.value = false
    uploadProgress.value = 0
  }
}

const clearForm = () => {
  text.value = ''
  files.value = []
  namespace.value = ''
  chunkingStrategy.value = 'recursive'
  metadata.value = null
  result.value = null
  uploadProgress.value = 0
  if (fileInput.value) fileInput.value.value = ''
  if (metadataRef.value) metadataRef.value.reset()
}
</script>

<style scoped>
.container {
  max-width: 800px;
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

.capture-form {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
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

textarea,
input[type="text"],
select {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 1rem;
  font-family: inherit;
  transition: border-color 0.2s;
}

textarea:focus,
input[type="text"]:focus,
select:focus {
  outline: none;
  border-color: #667eea;
}

textarea {
  resize: vertical;
  min-height: 120px;
}

select {
  background: white;
}

.hint {
  margin-top: 0.5rem;
  font-size: 0.875rem;
  color: #9ca3af;
}

.dropzone {
  border: 2px dashed #d1d5db;
  border-radius: 8px;
  padding: 1.5rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.dropzone:hover,
.dropzone.drag-over {
  border-color: #667eea;
  background: #f0f4ff;
}

.dropzone.has-file {
  border-style: solid;
  border-color: #667eea;
  background: #f0f4ff;
}

.dropzone-content p {
  margin: 0;
  color: #6b7280;
}

.dropzone-hint {
  font-size: 0.75rem;
  color: #9ca3af;
  margin-top: 0.25rem;
}

.file-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.file-icon {
  font-size: 1.5rem;
}

.file-name {
  font-weight: 500;
  color: #374151;
}

.file-clear {
  background: #ef4444;
  color: white;
  border: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.file-clear:hover {
  background: #dc2626;
}

.files-preview {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 100%;
}

.files-summary {
  font-size: 0.875rem;
  color: #6b7280;
  text-align: center;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e5e7eb;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 1rem;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  transition: width 0.3s ease;
}

.result.warning {
  background: #fef3c7;
  border: 1px solid #fcd34d;
}

.form-actions {
  display: flex;
  gap: 1rem;
}

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
}

/* Tablet breakpoint */
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

  .capture-form {
    padding: 1.25rem;
  }

  .form-group {
    margin-bottom: 1.25rem;
  }

  label {
    font-size: 0.9rem;
  }

  textarea,
  input[type="text"],
  select {
    font-size: 16px; /* Prevents zoom on iOS */
    min-height: 48px;
    padding: 0.875rem;
  }

  textarea {
    min-height: 100px;
  }

  .dropzone {
    padding: 1.25rem;
  }

  .dropzone-content p {
    font-size: 0.9rem;
  }

  .dropzone-hint {
    font-size: 0.7rem;
  }

  .file-preview {
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .file-name {
    font-size: 0.9rem;
    word-break: break-all;
  }

  .file-clear {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
  }

  .form-actions {
    flex-direction: column;
  }

  .form-actions .btn {
    width: 100%;
    min-height: 48px;
  }

  .result {
    flex-direction: column;
    gap: 0.75rem;
    text-align: center;
  }

  .result-icon {
    font-size: 2rem;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .page-header h1 {
    font-size: 1.5rem;
  }

  .page-header p {
    font-size: 0.9rem;
  }

  .page-header {
    margin-bottom: 1.5rem;
  }

  .capture-form {
    padding: 1rem;
  }

  textarea {
    min-height: 80px;
    rows: 4;
  }

  .hint {
    font-size: 0.8rem;
  }

  .file-icon {
    font-size: 1.25rem;
  }

  .files-preview {
    gap: 0.375rem;
  }

  .files-summary {
    font-size: 0.8rem;
  }
}
</style>
