<template>
  <NavDropdown label="Document Management" :items="items" />
</template>

<script setup>
import NavDropdown from './NavDropdown.vue'

const items = [
  { to: '/documents', icon: '📄', label: 'Documents' },
  { to: '/trash', icon: '🗑️', label: 'Trash' },
  { to: '/pending', icon: '⏳', label: 'Pending' },
  { to: '/namespaces', icon: '📁', label: 'Namespaces' }
]
</script>
