import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Home from './pages/Home.vue'
import Capture from './pages/Capture.vue'
import Query from './pages/Query.vue'
import Namespaces from './pages/Namespaces.vue'
import PendingQueue from './pages/PendingQueue.vue'
import auth, { authProvider } from './api/auth.js'

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
router.beforeEach(async (to, from, next) => {
  // Complete the OAuth code exchange first (authorization code + PKCE returns
  // ?code=... in the query). handleCallback is async: it hits the token
  // endpoint, so we MUST await it before the isAuthenticated check below, or
  // the guard would bounce to login and discard the code (the old loop).
  if (new URLSearchParams(window.location.search).has('code')) {
    await auth.handleCallback()
  }

  // Skip auth check if provider is 'none' (local dev)
  if (authProvider === 'none') {
    next()
    return
  }

  // Session expired but a refresh token is on hand -> renew silently rather
  // than full-redirecting to the Hosted UI.
  if (!auth.isAuthenticated() && auth.canRefresh?.()) {
    await auth.refresh()
  }

  // Still not authenticated -> start the login redirect.
  if (!auth.isAuthenticated()) {
    await auth.login()
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
