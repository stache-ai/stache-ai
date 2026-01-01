<template>
  <div class="app">
    <nav class="navbar">
      <div class="container">
        <div class="nav-brand">
          <h1>📎 Stache</h1>
          <p class="tagline">Your Personal Knowledge Base</p>
        </div>

        <!-- Hamburger menu button (mobile only) -->
        <button class="hamburger" @click="mobileMenuOpen = !mobileMenuOpen" aria-label="Toggle menu">
          <span class="hamburger-line" :class="{ open: mobileMenuOpen }"></span>
          <span class="hamburger-line" :class="{ open: mobileMenuOpen }"></span>
          <span class="hamburger-line" :class="{ open: mobileMenuOpen }"></span>
        </button>

        <!-- Desktop nav links -->
        <div class="nav-links desktop-nav">
          <router-link to="/" class="nav-link">Home</router-link>
          <router-link to="/capture" class="nav-link">Capture</router-link>
          <router-link to="/query" class="nav-link">Query</router-link>
          <router-link to="/pending" class="nav-link">Pending</router-link>
          <router-link to="/namespaces" class="nav-link">Namespaces</router-link>
        </div>

        <div class="nav-right desktop-nav">
          <div class="health-status" :class="healthStatus">
            <span class="status-dot"></span>
            {{ healthStatus === 'healthy' ? 'Connected' : 'Disconnected' }}
          </div>
          <AuthStatus />
        </div>
      </div>

      <!-- Mobile menu overlay -->
      <div class="mobile-menu" :class="{ open: mobileMenuOpen }" @click.self="mobileMenuOpen = false">
        <div class="mobile-menu-content">
          <router-link to="/" class="mobile-nav-link" @click="mobileMenuOpen = false">Home</router-link>
          <router-link to="/capture" class="mobile-nav-link" @click="mobileMenuOpen = false">Capture</router-link>
          <router-link to="/query" class="mobile-nav-link" @click="mobileMenuOpen = false">Query</router-link>
          <router-link to="/pending" class="mobile-nav-link" @click="mobileMenuOpen = false">Pending</router-link>
          <router-link to="/namespaces" class="mobile-nav-link" @click="mobileMenuOpen = false">Namespaces</router-link>
          <div class="mobile-health-status" :class="healthStatus">
            <span class="status-dot"></span>
            {{ healthStatus === 'healthy' ? 'Connected' : 'Disconnected' }}
          </div>
          <AuthStatus class="mobile-auth" />
        </div>
      </div>
    </nav>

    <main class="main-content">
      <router-view />
    </main>

    <footer class="footer">
      <div class="container">
        <p>Stache v0.1.0 | Powered by {{ llmProvider }}</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { checkHealth } from './api/client.js'
import { isAuthenticated, authProvider } from './api/auth.js'
import AuthStatus from './components/AuthStatus.vue'

const healthStatus = ref('unknown')
const llmProvider = ref('LLM')
const mobileMenuOpen = ref(false)
let healthCheckInterval = null

const checkHealthStatus = async () => {
  // Skip health check if auth is required but user isn't logged in
  if (authProvider !== 'none' && !isAuthenticated()) {
    healthStatus.value = 'unknown'
    return
  }

  try {
    // Use /api/health for authenticated users to get provider info
    // Use /api/ping for non-authenticated to avoid initializing providers
    const health = await checkHealth()
    if (health.status) {
      // Full health response with provider info
      healthStatus.value = health.status
      llmProvider.value = health.providers?.llm_provider || 'LLM'
    } else {
      // Ping response (just {ok: true})
      healthStatus.value = health.ok ? 'healthy' : 'unhealthy'
    }
  } catch (error) {
    healthStatus.value = 'unhealthy'
  }
}

onMounted(() => {
  checkHealthStatus()
  // Check health every 30 seconds
  healthCheckInterval = setInterval(checkHealthStatus, 30000)
})

onUnmounted(() => {
  if (healthCheckInterval) {
    clearInterval(healthCheckInterval)
    healthCheckInterval = null
  }
})
</script>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.navbar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 1rem 0;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
  position: relative;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.nav-brand h1 {
  font-size: 1.8rem;
  margin-bottom: 0.25rem;
}

.tagline {
  font-size: 0.9rem;
  opacity: 0.9;
}

/* Hamburger menu button */
.hamburger {
  display: none;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  width: 44px;
  height: 44px;
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  padding: 10px;
}

.hamburger-line {
  width: 24px;
  height: 3px;
  background: white;
  border-radius: 2px;
  transition: all 0.3s ease;
}

.hamburger-line.open:nth-child(1) {
  transform: rotate(45deg) translate(5px, 6px);
}

.hamburger-line.open:nth-child(2) {
  opacity: 0;
}

.hamburger-line.open:nth-child(3) {
  transform: rotate(-45deg) translate(5px, -6px);
}

/* Desktop nav */
.nav-links {
  display: flex;
  gap: 2rem;
}

.nav-link {
  color: white;
  text-decoration: none;
  font-weight: 500;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  transition: background 0.2s;
}

.nav-link:hover,
.nav-link.router-link-active {
  background: rgba(255, 255, 255, 0.2);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.health-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.2);
  font-size: 0.9rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.health-status.healthy .status-dot {
  background: #4ade80;
  box-shadow: 0 0 8px #4ade80;
}

.health-status.unhealthy .status-dot {
  background: #f87171;
}

/* Mobile menu */
.mobile-menu {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.3s, visibility 0.3s;
}

.mobile-menu.open {
  opacity: 1;
  visibility: visible;
}

.mobile-menu-content {
  position: absolute;
  top: 0;
  right: 0;
  width: 280px;
  max-width: 80%;
  height: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 2rem 1.5rem;
  transform: translateX(100%);
  transition: transform 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.mobile-menu.open .mobile-menu-content {
  transform: translateX(0);
}

.mobile-nav-link {
  color: white;
  text-decoration: none;
  font-weight: 500;
  font-size: 1.1rem;
  padding: 1rem;
  border-radius: 8px;
  transition: background 0.2s;
}

.mobile-nav-link:hover,
.mobile-nav-link.router-link-active {
  background: rgba(255, 255, 255, 0.2);
}

.mobile-health-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  margin-top: auto;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.2);
  font-size: 0.9rem;
}

.mobile-auth {
  padding: 1rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
}

.main-content {
  flex: 1;
  padding: 2rem 0;
}

.footer {
  background: #1f2937;
  color: #9ca3af;
  padding: 1.5rem 0;
  text-align: center;
}

.footer .container {
  padding: 0 1rem;
}

/* Tablet breakpoint */
@media (max-width: 900px) {
  .nav-links {
    gap: 1rem;
  }

  .nav-link {
    padding: 0.5rem 0.75rem;
    font-size: 0.9rem;
  }
}

/* Mobile breakpoint */
@media (max-width: 768px) {
  .container {
    padding: 0 1rem;
  }

  .nav-brand h1 {
    font-size: 1.4rem;
  }

  .tagline {
    font-size: 0.75rem;
  }

  .hamburger {
    display: flex;
  }

  .desktop-nav,
  .desktop-health {
    display: none;
  }

  .mobile-menu {
    display: block;
  }

  .main-content {
    padding: 1rem 0;
  }

  .footer {
    padding: 1rem 0;
    font-size: 0.85rem;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .nav-brand h1 {
    font-size: 1.2rem;
  }

  .tagline {
    display: none;
  }
}
</style>
