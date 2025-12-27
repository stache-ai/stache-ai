<template>
  <div class="tree-node">
    <div
      class="node-content"
      :class="{ selected: isSelected, 'has-children': hasChildren }"
      @click="$emit('select', node)"
    >
      <button
        v-if="hasChildren"
        class="toggle-btn"
        @click.stop="expanded = !expanded"
      >
        {{ expanded ? '▼' : '▶' }}
      </button>
      <span v-else class="toggle-spacer"></span>
      <span class="node-icon">{{ hasChildren ? '📁' : '📄' }}</span>
      <span class="node-name">{{ node.name }}</span>
      <span v-if="node.doc_count" class="node-count">{{ node.doc_count }}</span>
    </div>
    <div v-if="hasChildren && expanded" class="children">
      <NamespaceTreeNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :selected-id="selectedId"
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
    default: null
  }
})

defineEmits(['select'])

const expanded = ref(true)

const hasChildren = computed(() => {
  return props.node.children && props.node.children.length > 0
})

const isSelected = computed(() => {
  return props.selectedId === props.node.id
})
</script>

<style scoped>
.tree-node {
  user-select: none;
}

.node-content {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.5rem;
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
}
</style>
