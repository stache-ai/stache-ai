<template>
  <div class="tree-node">
    <div
      class="node-content"
      :class="{ selected: isSelected }"
      @click="handleSelect"
    >
      <button
        v-if="hasChildren"
        class="toggle-btn"
        @click.stop="toggleExpanded"
      >
        {{ expanded ? '▼' : '▶' }}
      </button>
      <span v-else class="toggle-spacer"></span>

      <span class="node-icon">{{ hasChildren ? '📁' : '📄' }}</span>
      <span class="node-name">{{ node.name || node.id }}</span>
      <span v-if="node.doc_count > 0" class="node-count">{{ node.doc_count }}</span>
    </div>

    <div v-if="hasChildren && expanded" class="children">
      <NamespaceTreeDropdownNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :selected-value="selectedValue"
        :search-query="searchQuery"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  selectedValue: {
    type: String,
    default: ''
  },
  searchQuery: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['select'])

const expanded = ref(false)

const hasChildren = computed(() => {
  return props.node.children && props.node.children.length > 0
})

const isSelected = computed(() => {
  return props.selectedValue === props.node.id
})

const toggleExpanded = () => {
  expanded.value = !expanded.value
}

const handleSelect = () => {
  emit('select', props.node.id)
}

// Auto-expand if search query matches or children match
watch(() => props.searchQuery, (newQuery) => {
  if (newQuery && hasChildren.value) {
    const query = newQuery.toLowerCase()
    const matchesThis = (props.node.name || '').toLowerCase().includes(query) ||
                       (props.node.id || '').toLowerCase().includes(query)

    const childrenMatch = props.node.children?.some(child => {
      const matchesChild = (child.name || '').toLowerCase().includes(query) ||
                          (child.id || '').toLowerCase().includes(query)
      return matchesChild
    })

    if (matchesThis || childrenMatch) {
      expanded.value = true
    }
  }
}, { immediate: true })
</script>

<style scoped>
.tree-node {
  user-select: none;
}

.node-content {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.node-content:hover {
  background: #f3f4f6;
}

.node-content.selected {
  background: #ede9fe;
  color: #5b21b6;
}

.toggle-btn {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.6rem;
  color: #9ca3af;
  padding: 0;
  flex-shrink: 0;
}

.toggle-btn:hover {
  color: #374151;
}

.toggle-spacer {
  width: 18px;
  flex-shrink: 0;
}

.node-icon {
  font-size: 0.9rem;
  flex-shrink: 0;
}

.node-name {
  flex: 1;
  font-size: 0.875rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-count {
  font-size: 0.7rem;
  background: #e5e7eb;
  color: #6b7280;
  padding: 0.125rem 0.375rem;
  border-radius: 10px;
  flex-shrink: 0;
}

.node-content.selected .node-count {
  background: #c4b5fd;
  color: #5b21b6;
}

.children {
  margin-left: 1rem;
  border-left: 1px solid #e5e7eb;
  padding-left: 0.25rem;
  margin-top: 0.25rem;
}
</style>
