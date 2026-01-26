<template>
  <div class="tree-dropdown" ref="dropdownRef">
    <button
      type="button"
      class="dropdown-toggle"
      :class="{ open: isOpen }"
      @click="toggleDropdown"
    >
      <span class="selected-text">{{ displayText }}</span>
      <span class="dropdown-arrow">{{ isOpen ? '▲' : '▼' }}</span>
    </button>

    <div v-if="isOpen" class="dropdown-menu">
      <div class="dropdown-header">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search namespaces..."
          class="search-input"
          @click.stop
        />
      </div>

      <div class="tree-container">
        <div
          v-if="allowEmpty"
          class="tree-option"
          :class="{ selected: modelValue === '' }"
          @click="selectNamespace('')"
        >
          <span class="option-icon">🌐</span>
          <span class="option-name">{{ emptyLabel }}</span>
        </div>

        <div v-if="tree.length === 0 && !searchQuery" class="loading-state">
          Loading namespaces...
        </div>

        <NamespaceTreeDropdownNode
          v-for="node in filteredTree"
          :key="node.id"
          :node="node"
          :selected-value="modelValue"
          :search-query="searchQuery"
          @select="selectNamespace"
        />

        <div v-if="filteredTree.length === 0 && searchQuery" class="no-results">
          No namespaces match "{{ searchQuery }}"
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import NamespaceTreeDropdownNode from './NamespaceTreeDropdownNode.vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  tree: {
    type: Array,
    required: true
  },
  flatNamespaces: {
    type: Array,
    required: true
  },
  allowEmpty: {
    type: Boolean,
    default: true
  },
  emptyLabel: {
    type: String,
    default: 'All Namespaces'
  },
  placeholder: {
    type: String,
    default: 'Select namespace...'
  }
})

const emit = defineEmits(['update:modelValue'])

const dropdownRef = ref(null)
const isOpen = ref(false)
const searchQuery = ref('')

const displayText = computed(() => {
  if (!props.modelValue) {
    return props.emptyLabel
  }

  const namespace = props.flatNamespaces.find(ns => ns.id === props.modelValue)
  return namespace ? (namespace.name || namespace.id) : props.modelValue
})

const filteredTree = computed(() => {
  if (!searchQuery.value.trim()) {
    return props.tree
  }

  const query = searchQuery.value.toLowerCase()

  const filterNode = (node) => {
    const matchesName = (node.name || '').toLowerCase().includes(query)
    const matchesId = (node.id || '').toLowerCase().includes(query)

    if (matchesName || matchesId) {
      return { ...node }
    }

    if (node.children && node.children.length > 0) {
      const filteredChildren = node.children
        .map(filterNode)
        .filter(Boolean)

      if (filteredChildren.length > 0) {
        return {
          ...node,
          children: filteredChildren
        }
      }
    }

    return null
  }

  return props.tree.map(filterNode).filter(Boolean)
})

const toggleDropdown = () => {
  isOpen.value = !isOpen.value
  if (!isOpen.value) {
    searchQuery.value = ''
  }
}

const selectNamespace = (namespaceId) => {
  emit('update:modelValue', namespaceId)
  isOpen.value = false
  searchQuery.value = ''
}

// Close dropdown when clicking outside
const handleClickOutside = (event) => {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target)) {
    isOpen.value = false
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
.tree-dropdown {
  position: relative;
  width: 100%;
}

.dropdown-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  background: white;
  font-size: 1rem;
  cursor: pointer;
  transition: border-color 0.2s;
  text-align: left;
}

.dropdown-toggle:hover {
  border-color: #d1d5db;
}

.dropdown-toggle.open,
.dropdown-toggle:focus {
  border-color: #667eea;
  outline: none;
}

.selected-text {
  flex: 1;
  color: #1f2937;
}

.dropdown-arrow {
  color: #9ca3af;
  font-size: 0.75rem;
  margin-left: 0.5rem;
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 0.25rem);
  left: 0;
  right: 0;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  max-height: 400px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.dropdown-header {
  padding: 0.75rem;
  border-bottom: 1px solid #e5e7eb;
}

.search-input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 0.875rem;
}

.search-input:focus {
  outline: none;
  border-color: #667eea;
}

.tree-container {
  overflow-y: auto;
  max-height: 320px;
  padding: 0.5rem;
}

.tree-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.tree-option:hover {
  background: #f3f4f6;
}

.tree-option.selected {
  background: #ede9fe;
  color: #5b21b6;
}

.option-icon {
  font-size: 0.9rem;
}

.option-name {
  font-size: 0.875rem;
  font-weight: 500;
}

.no-results,
.loading-state {
  padding: 1rem;
  text-align: center;
  color: #9ca3af;
  font-size: 0.875rem;
}
</style>
