<template>
  <div class="dropdown" :class="{ open: isOpen }" @mouseenter="handleMouseEnter" @mouseleave="handleMouseLeave">
    <button class="dropdown-toggle" @click="toggleDropdown" :class="{ active: isActiveRoute }">
      Document Management
      <span class="dropdown-arrow">▼</span>
    </button>
    <div class="dropdown-menu" v-show="isOpen">
      <div class="dropdown-menu-inner">
        <router-link to="/documents" class="dropdown-item" @click="closeDropdown">
          <span class="item-icon">📄</span>
          <span class="item-label">Documents</span>
        </router-link>
        <router-link to="/trash" class="dropdown-item" @click="closeDropdown">
          <span class="item-icon">🗑️</span>
          <span class="item-label">Trash</span>
        </router-link>
        <router-link to="/pending" class="dropdown-item" @click="closeDropdown">
          <span class="item-icon">⏳</span>
          <span class="item-label">Pending</span>
        </router-link>
        <router-link to="/namespaces" class="dropdown-item" @click="closeDropdown">
          <span class="item-icon">📁</span>
          <span class="item-label">Namespaces</span>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isOpen = ref(false)

// Check if any of the doc management routes are active
const isActiveRoute = computed(() => {
  const managementRoutes = ['/documents', '/trash', '/pending', '/namespaces']
  return managementRoutes.some(r => route.path.startsWith(r))
})

const toggleDropdown = () => {
  isOpen.value = !isOpen.value
}

const closeDropdown = () => {
  isOpen.value = false
}

// Desktop hover behavior
const handleMouseEnter = () => {
  isOpen.value = true
}

const handleMouseLeave = () => {
  isOpen.value = false
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
