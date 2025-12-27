<template>
  <div class="metadata-section">
    <!-- Tags -->
    <div class="form-group">
      <label>Tags (optional)</label>
      <input
        v-model="tagsInput"
        type="text"
        placeholder="e.g. kubernetes, programming, ideas"
        @keydown.enter.prevent="addTag"
      />
      <div class="tags-list">
        <span v-for="tag in tags" :key="tag" class="tag">
          {{ tag }}
          <button type="button" @click="removeTag(tag)" class="tag-remove">×</button>
        </span>
      </div>
    </div>

    <!-- Custom Attributes -->
    <div class="attributes-section">
      <div class="attributes-header">
        <label>Custom Attributes</label>
        <button type="button" @click="addField" class="add-btn">+ Add</button>
      </div>

      <div v-for="(field, index) in fields" :key="index" class="attribute-row">
        <input
          v-model="field.key"
          type="text"
          placeholder="Key"
          class="key-input"
          @input="emitUpdate"
        />
        <input
          v-model="field.value"
          type="text"
          placeholder="Value"
          class="value-input"
          @input="emitUpdate"
        />
        <button type="button" @click="removeField(index)" class="remove-btn">×</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const emit = defineEmits(['update:modelValue'])

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => null
  }
})

const tagsInput = ref('')
const tags = ref([])
const fields = ref([])

// Initialize from modelValue
watch(() => props.modelValue, (newVal) => {
  if (newVal) {
    // Extract tags array
    if (Array.isArray(newVal.tags)) {
      tags.value = [...newVal.tags]
    }
    // Extract other fields
    fields.value = Object.entries(newVal)
      .filter(([key]) => key !== 'tags')
      .map(([key, value]) => ({ key, value }))
  }
}, { immediate: true })

const addTag = () => {
  const tag = tagsInput.value.trim()
  if (tag && !tags.value.includes(tag)) {
    tags.value.push(tag)
    tagsInput.value = ''
    emitUpdate()
  }
}

const removeTag = (tag) => {
  tags.value = tags.value.filter(t => t !== tag)
  emitUpdate()
}

const addField = () => {
  fields.value.push({ key: '', value: '' })
}

const removeField = (index) => {
  fields.value.splice(index, 1)
  emitUpdate()
}

const emitUpdate = () => {
  const metadata = {}

  // Add tags if any
  if (tags.value.length > 0) {
    metadata.tags = [...tags.value]
  }

  // Add custom fields
  for (const field of fields.value) {
    if (field.key.trim()) {
      metadata[field.key.trim()] = field.value
    }
  }

  emit('update:modelValue', Object.keys(metadata).length > 0 ? metadata : null)
}

// Expose reset method for parent components
defineExpose({
  reset: () => {
    tags.value = []
    tagsInput.value = ''
    fields.value = []
    emitUpdate()
  }
})
</script>

<style scoped>
.metadata-section {
  margin-bottom: 1.5rem;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.5rem;
}

.form-group input[type="text"] {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.2s;
}

.form-group input[type="text"]:focus {
  outline: none;
  border-color: #667eea;
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: #667eea;
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 20px;
  font-size: 0.875rem;
}

.tag-remove {
  background: none;
  border: none;
  color: white;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.attributes-section {
  margin-top: 1rem;
}

.attributes-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.attributes-header label {
  font-weight: 600;
  color: #374151;
}

.add-btn {
  background: #667eea;
  color: white;
  border: none;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.2s;
}

.add-btn:hover {
  background: #5a6fd6;
}

.attribute-row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.key-input,
.value-input {
  flex: 1;
  padding: 0.6rem 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 6px;
  font-size: 0.9rem;
  transition: border-color 0.2s;
}

.key-input {
  max-width: 40%;
}

.key-input:focus,
.value-input:focus {
  outline: none;
  border-color: #667eea;
}

.remove-btn {
  background: #ef4444;
  color: white;
  border: none;
  width: 36px;
  height: 36px;
  border-radius: 6px;
  font-size: 1.25rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  flex-shrink: 0;
}

.remove-btn:hover {
  background: #dc2626;
}
</style>
