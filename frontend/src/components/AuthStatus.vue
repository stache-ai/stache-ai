<template>
  <div v-if="showAuth" class="auth-status">
    <template v-if="user">
      <router-link to="/account" class="user-email" title="Account &amp; usage">{{ user.email }}</router-link>
      <button @click="handleLogout" class="auth-btn">Logout</button>
    </template>
    <template v-else>
      <button @click="handleLogin" class="auth-btn">Login</button>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import auth, { authProvider } from '../api/auth.js'

const showAuth = authProvider !== 'none'
const user = ref(null)

const handleLogin = () => auth.login()
const handleLogout = () => {
  auth.logout()
  user.value = null
}

onMounted(() => {
  // Handle OAuth callback if returning from login
  auth.handleCallback()
  user.value = auth.getUser()
})
</script>

<style scoped>
.auth-status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.user-email {
  font-size: 0.85rem;
  opacity: 0.9;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
  color: white;
  text-decoration: none;
  cursor: pointer;
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s, opacity 0.2s;
}

.user-email:hover,
.user-email.router-link-active {
  opacity: 1;
  border-bottom-color: rgba(255, 255, 255, 0.6);
}

.auth-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.2s;
}

.auth-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}
</style>
