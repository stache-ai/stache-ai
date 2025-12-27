<template>
  <div class="namespace-selector" ref="selectorRef">
    <label v-if="label">{{ label }}</label>
    <div class="selector-input" @click="toggleDropdown">
      <span class="selected-value" :class="{ placeholder: !modelValue }">
        {{ displayValue }}
      </span>
      <span class="dropdown-arrow">{{ dropdownOpen ? '▲' : '▼' }}</span>
    </div>

    <div v-if="dropdownOpen" class="dropdown">
      <div class="dropdown-header">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search or type new..."
          class="search-input"
          @click.stop
          ref="searchInput"
        />
        <button
          v-if="allowClear && modelValue"
          @click.stop="clearSelection"
          class="clear-btn"
          title="Clear selection"
        >
          ×
        </button>
      </div>

      <div class="dropdown-content">
        <div v-if="loading" class="loading-state">Loading namespaces...</div>

        <div v-else-if="filteredTree.length === 0 && !searchQuery" class="empty-state">
          No namespaces found. Type to create one.
        </div>

        <div v-else class="tree-container">
          <!-- Show "All namespaces" option for query mode -->
          <div
            v-if="showAllOption"
            class="tree-item root-item"
            :class="{ selected: !modelValue }"
            @click="selectNamespace(null)"
          >
            <span class="item-icon">🌐</span>
            <span class="item-name">All namespaces</span>
          </div>

          <NamespaceSelectorNode
            v-for="node in filteredTree"
            :key="node.id"
            :node="node"
            :selected-id="modelValue"
            :depth="0"
            @select="selectNamespace"
          />
        </div>

        <!-- Create new option when typing -->
        <div
          v-if="searchQuery && !exactMatch"
          class="create-option"
          @click="selectNamespace(searchQuery)"
        >
          <span class="create-icon">+</span>
          <span>Create "{{ searchQuery }}"</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { getNamespaceTree } from '../api/client.js'
import NamespaceSelectorNode from './NamespaceSelectorNode.vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  label: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: 'Select namespace...'
  },
  allowClear: {
    type: Boolean,
    default: true
  },
  showAllOption: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

const selectorRef = ref(null)
const searchInput = ref(null)
const dropdownOpen = ref(false)
const searchQuery = ref('')
const loading = ref(false)
const namespaceTree = ref([])

const displayValue = computed(() => {
  if (!props.modelValue) return props.placeholder
  return props.modelValue
})

const flattenTree = (nodes, prefix = '') => {
  const result = []
  for (const node of nodes) {
    const fullPath = prefix ? `${prefix}/${node.name}` : node.name
    result.push({ ...node, fullPath })
    if (node.children && node.children.length > 0) {
      result.push(...flattenTree(node.children, fullPath))
    }
  }
  return result
}

const filteredTree = computed(() => {
  if (!searchQuery.value) return namespaceTree.value

  const query = searchQuery.value.toLowerCase()
  const flat = flattenTree(namespaceTree.value)

  // Filter nodes that match the search
  const matchingIds = new Set()
  flat.forEach(node => {
    if (node.name.toLowerCase().includes(query) ||
        node.id.toLowerCase().includes(query)) {
      matchingIds.add(node.id)
      // Also add parent paths
      const parts = node.id.split('/')
      for (let i = 1; i < parts.length; i++) {
        matchingIds.add(parts.slice(0, i).join('/'))
      }
    }
  })

  // Rebuild tree with only matching nodes
  const filterNodes = (nodes) => {
    return nodes
      .filter(node => matchingIds.has(node.id))
      .map(node => ({
        ...node,
        children: node.children ? filterNodes(node.children) : []
      }))
  }

  return filterNodes(namespaceTree.value)
})

const exactMatch = computed(() => {
  if (!searchQuery.value) return true
  const flat = flattenTree(namespaceTree.value)
  return flat.some(node =>
    node.id.toLowerCase() === searchQuery.value.toLowerCase() ||
    node.name.toLowerCase() === searchQuery.value.toLowerCase()
  )
})

const loadNamespaces = async () => {
  loading.value = true
  try {
    const response = await getNamespaceTree(true)
    // API returns { tree: [...], count: N }
    namespaceTree.value = response.tree || []
  } catch (error) {
    console.error('Failed to load namespaces:', error)
    namespaceTree.value = []
  } finally {
    loading.value = false
  }
}

const toggleDropdown = () => {
  dropdownOpen.value = !dropdownOpen.value
  if (dropdownOpen.value) {
    loadNamespaces()
    nextTick(() => {
      searchInput.value?.focus()
    })
  }
}

const selectNamespace = (id) => {
  emit('update:modelValue', id || '')
  dropdownOpen.value = false
  searchQuery.value = ''
}

const clearSelection = () => {
  emit('update:modelValue', '')
  searchQuery.value = ''
}

// Close dropdown when clicking outside
const handleClickOutside = (event) => {
  if (selectorRef.value && !selectorRef.value.contains(event.target)) {
    dropdownOpen.value = false
    searchQuery.value = ''
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.namespace-selector {
  position: relative;
  width: 100%;
}

label {
  display: block;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.5rem;
}

.selector-input {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  transition: border-color 0.2s;
}

.selector-input:hover {
  border-color: #d1d5db;
}

.selected-value {
  flex: 1;
  font-size: 1rem;
  color: #1f2937;
}

.selected-value.placeholder {
  color: #9ca3af;
}

.dropdown-arrow {
  font-size: 0.7rem;
  color: #9ca3af;
  margin-left: 0.5rem;
}

.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  max-height: 350px;
  display: flex;
  flex-direction: column;
}

.dropdown-header {
  display: flex;
  align-items: center;
  padding: 0.5rem;
  border-bottom: 1px solid #e5e7eb;
  gap: 0.5rem;
}

.search-input {
  flex: 1;
  padding: 0.5rem;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 0.9rem;
}

.search-input:focus {
  outline: none;
  border-color: #667eea;
}

.clear-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 1.2rem;
  color: #6b7280;
}

.clear-btn:hover {
  background: #e5e7eb;
  color: #374151;
}

.dropdown-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
}

.loading-state,
.empty-state {
  padding: 1.5rem;
  text-align: center;
  color: #6b7280;
  font-size: 0.9rem;
}

.tree-container {
  min-height: 50px;
}

.tree-item.root-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 0.25rem;
}

.tree-item.root-item:hover {
  background: #f3f4f6;
}

.tree-item.root-item.selected {
  background: #ede9fe;
  color: #5b21b6;
}

.item-icon {
  font-size: 1rem;
}

.item-name {
  font-size: 0.9rem;
  font-weight: 500;
}

.create-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  margin-top: 0.5rem;
  border-top: 1px solid #e5e7eb;
  cursor: pointer;
  color: #667eea;
  font-weight: 500;
}

.create-option:hover {
  background: #f0f4ff;
  border-radius: 0 0 6px 6px;
}

.create-icon {
  font-size: 1.2rem;
  font-weight: bold;
}

/* Mobile breakpoint */
@media (max-width: 768px) {
  .selector-input {
    min-height: 48px;
    padding: 0.875rem;
  }

  .selected-value {
    font-size: 16px; /* Prevents zoom on iOS */
  }

  .dropdown {
    max-height: 300px;
  }

  .dropdown-header {
    padding: 0.75rem;
  }

  .search-input {
    min-height: 44px;
    font-size: 16px; /* Prevents zoom on iOS */
    padding: 0.625rem;
  }

  .clear-btn {
    width: 36px;
    height: 36px;
  }

  .dropdown-content {
    padding: 0.375rem;
  }

  .tree-item.root-item {
    min-height: 44px;
    padding: 0.625rem;
  }

  .item-name {
    font-size: 1rem;
  }

  .create-option {
    min-height: 48px;
    padding: 0.875rem;
  }

  .loading-state,
  .empty-state {
    padding: 1.25rem;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .dropdown {
    max-height: 250px;
  }
}
</style>
