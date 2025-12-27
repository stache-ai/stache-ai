<template>
  <div class="container">
    <div class="query-form">
      <div class="search-box">
        <input
          v-model="query"
          type="text"
          placeholder="Ask a question..."
          @keydown.enter="handleQuery"
          autofocus
        />
        <button
          @click="handleQuery"
          :disabled="!query.trim() || loading"
          class="search-btn"
        >
          {{ loading ? '...' : '🔍' }}
        </button>
      </div>

      <div class="options">
        <div class="options-row">
          <div class="namespace-selector-wrapper">
            <NamespaceSelector
              v-model="namespace"
              placeholder="All namespaces"
              :allow-clear="true"
              :show-all-option="true"
            />
          </div>
          <div class="top-k-selector">
            <label>Results:</label>
            <select v-model="topK">
              <option :value="5">5</option>
              <option :value="10">10</option>
              <option :value="15">15</option>
              <option :value="20">20</option>
            </select>
          </div>
          <label class="checkbox">
            <input type="checkbox" v-model="synthesize" />
            <span>AI synthesis</span>
          </label>
          <label class="checkbox">
            <input type="checkbox" v-model="rerank" />
            <span>Rerank results</span>
          </label>
        </div>
        <div v-if="synthesize && hasModelOptions" class="options-row model-row">
          <div class="model-selector">
            <label>Model:</label>
            <select v-model="selectedModel">
              <option value="">Default</option>
              <optgroup v-if="modelGroups.fast.length" label="Fast & Cheap">
                <option v-for="model in modelGroups.fast" :key="model.id" :value="model.id">
                  {{ model.name }}
                </option>
              </optgroup>
              <optgroup v-if="modelGroups.balanced.length" label="Balanced">
                <option v-for="model in modelGroups.balanced" :key="model.id" :value="model.id">
                  {{ model.name }}
                </option>
              </optgroup>
              <optgroup v-if="modelGroups.premium.length" label="Premium">
                <option v-for="model in modelGroups.premium" :key="model.id" :value="model.id">
                  {{ model.name }}
                </option>
              </optgroup>
            </select>
          </div>
        </div>
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>{{ synthesize ? 'Synthesizing answer...' : 'Searching...' }}</p>
      </div>

      <div v-if="!loading && result" class="results">
        <div v-if="synthesize && result.answer" class="answer-box">
          <h3>💡 Answer</h3>
          <div class="answer-content">{{ result.answer }}</div>
        </div>

        <div class="sources">
          <h3>📚 Sources ({{ sources.length }})</h3>
          <div v-if="sources.length === 0" class="no-results">
            <p>No relevant information found in your knowledge base.</p>
            <p class="hint">Try rephrasing your question or capture more information first.</p>
          </div>
          <div v-for="(source, index) in sources" :key="index" class="source-card">
            <div class="source-header">
              <span class="source-number">Source {{ index + 1 }}</span>
              <span v-if="source.score" class="source-score">
                {{ Math.round(source.score * 100) }}% match
              </span>
            </div>
            <div class="source-content">{{ source.text }}</div>
            <div v-if="source.metadata && Object.keys(source.metadata).length > 0" class="source-metadata">
              <span v-for="(value, key) in source.metadata" :key="key" class="metadata-tag">
                {{ key }}: {{ value }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="error" class="error">
        <div class="error-icon">❌</div>
        <div class="error-content">
          <strong>Query failed</strong>
          <p>{{ error }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { queryKnowledge, listModels } from '../api/client.js'
import NamespaceSelector from '../components/NamespaceSelector.vue'

const query = ref('')
const namespace = ref('')
const synthesize = ref(true)
const topK = ref(10)
const rerank = ref(false)
const selectedModel = ref('')
const loading = ref(false)
const result = ref(null)
const error = ref(null)

// Model selection state
const availableModels = ref([])
const modelGroups = ref({ fast: [], balanced: [], premium: [] })

const hasModelOptions = computed(() => availableModels.value.length > 0)

const sources = computed(() => {
  if (!result.value) return []
  // Backend always returns 'sources' key regardless of synthesize setting
  return result.value.sources || result.value.results || []
})

// Fetch available models on mount
onMounted(async () => {
  try {
    const data = await listModels()
    availableModels.value = data.models || []
    modelGroups.value = data.grouped || { fast: [], balanced: [], premium: [] }
  } catch (err) {
    console.warn('Failed to fetch models:', err)
    // Silently fail - model selector just won't show
  }
})

const handleQuery = async () => {
  if (!query.value.trim()) return

  loading.value = true
  error.value = null
  result.value = null

  try {
    const ns = namespace.value.trim() || null
    const model = selectedModel.value || null
    const response = await queryKnowledge(query.value, synthesize.value, topK.value, ns, rerank.value, model)
    result.value = response
  } catch (err) {
    error.value = err.response?.data?.detail || err.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.container {
  max-width: 900px;
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

.query-form {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.search-box {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.search-box input {
  flex: 1;
  padding: 1rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 1.1rem;
  transition: border-color 0.2s;
}

.search-box input:focus {
  outline: none;
  border-color: #667eea;
}

.search-btn {
  padding: 1rem 2rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1.5rem;
  cursor: pointer;
  transition: transform 0.2s;
}

.search-btn:hover:not(:disabled) {
  transform: translateY(-2px);
}

.search-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.options {
  margin-bottom: 1.5rem;
}

.options-row {
  display: flex;
  gap: 2rem;
  align-items: center;
  flex-wrap: wrap;
}

.namespace-selector-wrapper {
  min-width: 250px;
}

.top-k-selector {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.top-k-selector label {
  color: #374151;
  font-size: 0.9rem;
}

.top-k-selector select {
  padding: 0.4rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  cursor: pointer;
}

.model-row {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
}

.model-selector {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
}

.model-selector label {
  color: #374151;
  font-size: 0.9rem;
  white-space: nowrap;
}

.model-selector select {
  flex: 1;
  max-width: 300px;
  padding: 0.4rem 0.6rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  cursor: pointer;
  font-size: 0.9rem;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.checkbox input {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.checkbox span {
  color: #374151;
}

.loading {
  text-align: center;
  padding: 3rem;
  color: #6b7280;
}

.spinner {
  width: 50px;
  height: 50px;
  margin: 0 auto 1rem;
  border: 4px solid #e5e7eb;
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.results {
  margin-top: 2rem;
}

.answer-box {
  background: linear-gradient(135deg, #f0f4ff 0%, #e8f0fe 100%);
  padding: 1.5rem;
  border-radius: 12px;
  margin-bottom: 2rem;
  border-left: 4px solid #667eea;
}

.answer-box h3 {
  margin-bottom: 1rem;
  color: #1f2937;
}

.answer-content {
  color: #374151;
  line-height: 1.7;
  font-size: 1.1rem;
}

.sources h3 {
  margin-bottom: 1rem;
  color: #1f2937;
}

.no-results {
  text-align: center;
  padding: 3rem;
  color: #6b7280;
}

.no-results .hint {
  margin-top: 0.5rem;
  font-size: 0.9rem;
}

.source-card {
  background: #f9fafb;
  padding: 1.5rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  border-left: 3px solid #d1d5db;
}

.source-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.source-number {
  font-weight: 600;
  color: #667eea;
}

.source-score {
  background: #667eea;
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.875rem;
}

.source-content {
  color: #374151;
  line-height: 1.6;
  margin-bottom: 0.75rem;
}

.source-metadata {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.metadata-tag {
  background: #e5e7eb;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  color: #6b7280;
}

.error {
  margin-top: 1.5rem;
  padding: 1rem;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  border-radius: 8px;
  display: flex;
  gap: 1rem;
}

.error-icon {
  font-size: 1.5rem;
}

.error-content strong {
  display: block;
  margin-bottom: 0.25rem;
  color: #1f2937;
}

.error-content p {
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

  .query-form {
    padding: 1.25rem;
  }

  .search-box input {
    padding: 0.875rem;
    font-size: 1rem;
  }

  .search-btn {
    padding: 0.875rem 1.25rem;
    font-size: 1.25rem;
  }

  .options-row {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }

  .namespace-selector-wrapper {
    min-width: 100%;
  }

  .top-k-selector {
    justify-content: space-between;
    padding: 0.5rem 0;
  }

  .top-k-selector select {
    padding: 0.5rem 0.75rem;
    min-height: 44px;
  }

  .checkbox {
    padding: 0.5rem 0;
    min-height: 44px;
  }

  .checkbox input {
    width: 22px;
    height: 22px;
  }

  .answer-box {
    padding: 1rem;
  }

  .answer-content {
    font-size: 1rem;
  }

  .source-card {
    padding: 1rem;
  }

  .source-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
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

  .search-box {
    flex-direction: column;
  }

  .search-btn {
    width: 100%;
    min-height: 48px;
  }

  .loading {
    padding: 2rem 1rem;
  }

  .spinner {
    width: 40px;
    height: 40px;
  }

  .no-results {
    padding: 2rem 1rem;
  }
}
</style>
