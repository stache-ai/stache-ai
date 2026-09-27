<template>
  <div class="dropdown" :class="{ open: isOpen }" @mouseenter="isOpen = true" @mouseleave="isOpen = false">
    <button class="dropdown-toggle" @click="isOpen = !isOpen" :class="{ active: isActiveRoute }">
      {{ label }}
      <span class="dropdown-arrow">▼</span>
    </button>
    <div class="dropdown-menu" v-show="isOpen">
      <div class="dropdown-menu-inner">
        <template v-for="item in items" :key="item.id || item.to">
          <router-link v-if="item.to" :to="item.to" class="dropdown-item" @click="close">
            <span v-if="hasIcons" class="item-icon">{{ item.icon }}</span>
            <span class="item-label">{{ item.label }}</span>
          </router-link>
          <a
            v-else
            :href="item.href"
            :target="item.newTab ? '_blank' : undefined"
            :rel="item.newTab ? 'noopener noreferrer' : undefined"
            class="dropdown-item"
            @click="close"
          >
            <span v-if="hasIcons" class="item-icon">{{ item.icon }}</span>
            <span class="item-label">{{ item.label }}</span>
          </a>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

// items: [{ label, icon?, to? (router path) | href? (plain link), newTab? }]
const props = defineProps({
  label: { type: String, required: true },
  items: { type: Array, required: true }
})

const emit = defineEmits(['navigate'])

const route = useRoute()
const isOpen = ref(false)

// Highlight the toggle when any router item is active
const isActiveRoute = computed(() =>
  props.items.some(item => item.to && route.path.startsWith(item.to))
)

// Reserve the icon column only if some item has an icon
const hasIcons = computed(() => props.items.some(item => item.icon))

const close = () => {
  isOpen.value = false
  emit('navigate')
}
</script>

<style scoped>
.dropdown {
  position: relative;
  display: inline-block;
}

.dropdown-toggle {
  color: white;
  background: transparent;
  border: none;
  font-weight: 500;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
}

.dropdown-toggle:hover,
.dropdown-toggle.active,
.dropdown.open .dropdown-toggle {
  background: rgba(255, 255, 255, 0.2);
}

.dropdown-arrow {
  font-size: 0.7rem;
  transition: transform 0.2s;
}

.dropdown.open .dropdown-arrow {
  transform: rotate(180deg);
}

.dropdown-menu {
  position: absolute;
  top: 100%;
  left: 0;
  padding-top: 0.5rem;
  min-width: 200px;
  z-index: 1000;
}

.dropdown-menu-inner {
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  color: #374151;
  text-decoration: none;
  transition: background 0.2s;
}

.dropdown-item:hover,
.dropdown-item.router-link-active {
  background: #f3f4f6;
  color: #667eea;
}

.item-icon {
  font-size: 1.2rem;
  width: 24px;
  text-align: center;
}

.item-label {
  font-weight: 500;
}

/* Mobile styles */
@media (max-width: 768px) {
  .dropdown {
    width: 100%;
  }

  .dropdown-toggle {
    width: 100%;
    justify-content: space-between;
    padding: 1rem;
    font-size: 1.1rem;
  }

  .dropdown-menu {
    position: static;
    padding-top: 0;
  }

  .dropdown-menu-inner {
    box-shadow: none;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 0;
  }

  .dropdown-item {
    color: white;
    padding: 0.75rem 1.5rem;
  }

  .dropdown-item:hover,
  .dropdown-item.router-link-active {
    background: rgba(255, 255, 255, 0.15);
    color: white;
  }
}
</style>
