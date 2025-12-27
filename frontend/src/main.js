import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Home from './pages/Home.vue'
import Capture from './pages/Capture.vue'
import Query from './pages/Query.vue'
import Namespaces from './pages/Namespaces.vue'
import PendingQueue from './pages/PendingQueue.vue'
import auth, { authProvider, handleCallback } from './api/auth.js'

const routes = [
  { path: '/', component: Home },
  { path: '/capture', component: Capture },
  { path: '/query', component: Query },
  { path: '/namespaces', component: Namespaces },
  { path: '/pending', component: PendingQueue },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Auth guard - only enforced when auth provider is configured (not 'none')
router.beforeEach((to, from, next) => {
  // Handle OAuth callback first (token in URL hash)
  if (window.location.hash.includes('id_token=')) {
    handleCallback()
  }

  // Skip auth check if provider is 'none' (local dev)
  if (authProvider === 'none') {
    next()
    return
  }

  // If not authenticated, trigger login
  if (!auth.isAuthenticated()) {
    auth.login()
    return
  }

  next()
})

const app = createApp(App)

// Global error handler to prevent blank screens
app.config.errorHandler = (err, instance, info) => {
  console.error('Vue Error:', err)
  console.error('Component:', instance)
  console.error('Info:', info)
}

// Handle unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled Promise Rejection:', event.reason)
})

app.use(router)
app.mount('#app')
