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

// After this many failed sign-in attempts we stop redirecting to the Hosted UI
// (a valid Cognito session cookie makes each /authorize return instantly, so a
// persistent exchange failure / ?error would otherwise be a redirect storm).
const MAX_AUTH_ATTEMPTS = 2

// Auth guard - only enforced when auth provider is configured (not 'none')
router.beforeEach(async (to, from, next) => {
  // OAuth callback: complete the code exchange (or capture an ?error), then
  // strip the oauth params from the URL THROUGH the router. Key off to.query,
  // not window.location: the router resolves `to` before guards run and would
  // otherwise re-insert ?code=... after next(), leaving the code in history
  // (a spurious state-mismatch on the next reload).
  if (authProvider === 'cognito' && (to.query.code || to.query.error)) {
    const ok = await auth.handleCallback()
    // eslint-disable-next-line no-unused-vars
    const { code, state, error, error_description, ...rest } = to.query
    if (ok) {
      sessionStorage.removeItem('stache_auth_attempts')
      const dest = sessionStorage.getItem('stache_post_login')
      sessionStorage.removeItem('stache_post_login')
      return next(dest && dest !== to.fullPath ? dest : { path: to.path, query: rest, replace: true })
    }
    return next({ path: to.path, query: rest, replace: true })
  }

  // Skip auth check if provider is 'none' (local dev)
  if (authProvider === 'none') return next()

  if (auth.isAuthenticated()) {
    sessionStorage.removeItem('stache_auth_attempts')
    return next()
  }

  // Session expired but a refresh token is on hand -> renew silently
  // (single-flight in auth.js) rather than full-redirecting to the Hosted UI.
  if (auth.canRefresh?.()) {
    await auth.refresh()
    if (auth.isAuthenticated()) {
      sessionStorage.removeItem('stache_auth_attempts')
      return next()
    }
  }

  // Not authenticated. Circuit breaker: after repeated failures, render the app
  // unauthenticated instead of looping back to the Hosted UI. Resets on a
  // successful sign-in; the counter is in sessionStorage, so it survives a
  // reload but not closing the tab.
  const attempts = parseInt(sessionStorage.getItem('stache_auth_attempts') || '0', 10)
  if (attempts >= MAX_AUTH_ATTEMPTS) {
    console.error('Sign-in failed repeatedly; not retrying. Use the Login button to try again.')
    return next()
  }
  sessionStorage.setItem('stache_auth_attempts', String(attempts + 1))
  try { sessionStorage.setItem('stache_post_login', to.fullPath) } catch { /* ignore */ }
  // login() returns true when it initiated a redirect; if it bailed (not
  // configured, no crypto.subtle, prompt cancelled), render the app rather than
  // hang the never-settling navigation (a blank page under the deferred mount).
  if (!(await auth.login())) return next()
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
// Mount only after the initial navigation (and any code exchange) resolves, so
// components outside <router-view> (the header AuthStatus) don't render in a
// stale unauthenticated state right after login. If the guard triggers a login
// redirect, isReady never resolves and the page is unloading anyway.
router.isReady()
  .catch((e) => console.error('Router initialization failed', e))
  .then(() => app.mount('#app'))
