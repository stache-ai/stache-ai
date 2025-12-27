<template>
  <div class="selector-node">
    <div
      class="node-row"
      :class="{ selected: isSelected }"
      :style="{ paddingLeft: depth * 16 + 8 + 'px' }"
      @click="$emit('select', node.id)"
    >
      <button
        v-if="hasChildren"
        class="expand-btn"
        @click.stop="expanded = !expanded"
      >
        {{ expanded ? '▼' : '▶' }}
      </button>
      <span v-else class="expand-spacer"></span>
      <span class="node-icon">{{ hasChildren ? '📁' : '📄' }}</span>
      <span class="node-label">{{ node.name }}</span>
      <span v-if="node.doc_count" class="doc-count">{{ node.doc_count }}</span>
    </div>
    <div v-if="hasChildren && expanded" class="children">
      <NamespaceSelectorNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :selected-id="selectedId"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  selectedId: {
    type: String,
    default: ''
  },
  depth: {
    type: Number,
    default: 0
  }
})

defineEmits(['select'])

const expanded = ref(props.depth < 2) // Auto-expand first 2 levels

const hasChildren = computed(() => {
  return props.node.children && props.node.children.length > 0
})

const isSelected = computed(() => {
  return props.selectedId === props.node.id
})
</script>

<style scoped>
.selector-node {
  user-select: none;
}

.node-row {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.4rem 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.node-row:hover {
  background: #f3f4f6;
}

.node-row.selected {
  background: #ede9fe;
  color: #5b21b6;
}

.expand-btn {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.55rem;
  color: #9ca3af;
  padding: 0;
  flex-shrink: 0;
}

.expand-btn:hover {
  color: #374151;
}

.expand-spacer {
  width: 16px;
  flex-shrink: 0;
}

.node-icon {
  font-size: 0.85rem;
  flex-shrink: 0;
}

.node-label {
  flex: 1;
  font-size: 0.875rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-count {
  font-size: 0.65rem;
  background: #e5e7eb;
  color: #6b7280;
  padding: 0.1rem 0.35rem;
  border-radius: 8px;
  flex-shrink: 0;
}

.node-row.selected .doc-count {
  background: #c4b5fd;
  color: #5b21b6;
}

.children {
  border-left: 1px solid #e5e7eb;
  margin-left: 16px;
}
</style>
