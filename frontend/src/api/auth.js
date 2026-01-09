/**
 * Authentication Factory
 *
 * Supports multiple auth providers:
 * - 'none': No auth (local dev, air-gapped)
 * - 'cognito': AWS Cognito OAuth2 implicit flow
 * - 'apikey': Static API key (simple deployments)
 *
 * Configuration sources (in priority order):
 * 1. Runtime: /config.json (for pre-built packages)
 * 2. Build-time: VITE_* environment variables
 */

import { getConfig, loadConfig } from '../config.js'

// Will be set after config loads
let authInstance = null
let authProviderType = null

/**
 * No-op auth provider (always authenticated, no tokens)
 */
const noAuthProvider = {
  isConfigured: () => true,
  isAuthenticated: () => true,
  getToken: () => null,
  getUser: () => ({ email: 'local@dev', name: 'Local User' }),
  login: () => {},
  logout: () => window.location.reload(),
  handleCallback: () => false,
  getAuthHeader: () => ({}),
}

/**
 * API Key auth provider
 */
function createApiKeyProvider() {
  const API_KEY = getConfig('API_KEY') || localStorage.getItem('stache_api_key') || ''

  return {
    isConfigured: () => !!API_KEY,
    isAuthenticated: () => !!API_KEY,
    getToken: () => API_KEY,
    getUser: () => API_KEY ? { email: 'api-key-user', name: 'API Key User' } : null,
    login: () => {
      const key = prompt('Enter API Key:')
      if (key) {
        localStorage.setItem('stache_api_key', key)
        window.location.reload()
      }
    },
    logout: () => {
      localStorage.removeItem('stache_api_key')
      window.location.reload()
    },
    handleCallback: () => false,
    getAuthHeader: () => API_KEY ? { 'X-Api-Key': API_KEY } : {},
  }
}

/**
 * Cognito OAuth2 implicit flow provider
 */
function createCognitoProvider() {
  const config = {
    region: getConfig('AWS_REGION', 'us-east-1'),
    userPoolId: getConfig('COGNITO_USER_POOL_ID', ''),
    clientId: getConfig('COGNITO_CLIENT_ID', ''),
    domain: getConfig('COGNITO_DOMAIN', ''),
    redirectUri: getConfig('COGNITO_REDIRECT_URI') || window.location.origin,
  }

  const TOKEN_KEY = 'stache_id_token'
  const EXPIRY_KEY = 'stache_token_expiry'

  const isConfigured = () => !!(config.domain && config.clientId)

  const isAuthenticated = () => {
    const token = localStorage.getItem(TOKEN_KEY)
    const expiry = localStorage.getItem(EXPIRY_KEY)
    if (!token || !expiry) return false
    // Check expiry with 5 minute buffer
    return Date.now() < (parseInt(expiry, 10) - 5 * 60 * 1000)
  }

  const getToken = () => {
    if (!isAuthenticated()) return null
    return localStorage.getItem(TOKEN_KEY)
  }

  const getUser = () => {
    const token = getToken()
    if (!token) return null
    try {
      const payload = token.split('.')[1]
      const decoded = JSON.parse(atob(payload))
      return {
        email: decoded.email,
        sub: decoded.sub,
        name: decoded.name || decoded.email,
      }
    } catch {
      return null
    }
  }

  const login = () => {
    if (!isConfigured()) {
      console.error('Cognito not configured. Ensure config.json or VITE_COGNITO_* variables are set.')
      return
    }
    const loginUrl = new URL(`https://${config.domain}/login`)
    loginUrl.searchParams.set('client_id', config.clientId)
    loginUrl.searchParams.set('response_type', 'token')
    loginUrl.searchParams.set('scope', 'email openid profile')
    loginUrl.searchParams.set('redirect_uri', config.redirectUri)
    window.location.href = loginUrl.toString()
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(EXPIRY_KEY)
    if (!isConfigured()) {
      window.location.reload()
      return
    }
    const logoutUrl = new URL(`https://${config.domain}/logout`)
    logoutUrl.searchParams.set('client_id', config.clientId)
    logoutUrl.searchParams.set('logout_uri', config.redirectUri)
    window.location.href = logoutUrl.toString()
  }

  const handleCallback = () => {
    const hash = window.location.hash
    if (!hash || !hash.includes('id_token=')) return false

    const params = new URLSearchParams(hash.substring(1))
    const idToken = params.get('id_token')
    const expiresIn = params.get('expires_in')

    if (idToken) {
      const expiryTime = Date.now() + (parseInt(expiresIn || '3600', 10) * 1000)
      localStorage.setItem(TOKEN_KEY, idToken)
      localStorage.setItem(EXPIRY_KEY, expiryTime.toString())
      window.history.replaceState(null, '', window.location.pathname)
      return true
    }
    return false
  }

  const getAuthHeader = () => {
    const token = getToken()
    return token ? { 'Authorization': `Bearer ${token}` } : {}
  }

  return {
    isConfigured,
    isAuthenticated,
    getToken,
    getUser,
    login,
    logout,
    handleCallback,
    getAuthHeader,
  }
}

/**
 * Create auth provider based on configuration
 */
function createAuthProvider() {
  const provider = getConfig('AUTH_PROVIDER', 'none')
  authProviderType = provider.toLowerCase()

  switch (authProviderType) {
    case 'cognito':
      return createCognitoProvider()
    case 'apikey':
      return createApiKeyProvider()
    case 'none':
    default:
      return noAuthProvider
  }
}

/**
 * Initialize auth - must be called after config is loaded
 */
export async function initAuth() {
  await loadConfig()
  authInstance = createAuthProvider()
  return authInstance
}

/**
 * Get auth instance (throws if not initialized)
 */
function getAuth() {
  if (!authInstance) {
    // Fallback: create with whatever config is available
    authInstance = createAuthProvider()
  }
  return authInstance
}

// Named exports for convenience
export const isConfigured = () => getAuth().isConfigured()
export const isAuthenticated = () => getAuth().isAuthenticated()
export const getToken = () => getAuth().getToken()
export const getUser = () => getAuth().getUser()
export const login = () => getAuth().login()
export const logout = () => getAuth().logout()
export const handleCallback = () => getAuth().handleCallback()
export const getAuthHeader = () => getAuth().getAuthHeader()
export const getAuthProvider = () => authProviderType || getConfig('AUTH_PROVIDER', 'none').toLowerCase()

// Legacy export for backwards compatibility
// Note: This is evaluated at import time, so it only reflects build-time config.
// Use getAuthProvider() for runtime config support.
export const authProvider = import.meta.env.VITE_AUTH_PROVIDER || 'none'

export default {
  initAuth,
  isConfigured,
  isAuthenticated,
  getToken,
  getUser,
  login,
  logout,
  handleCallback,
  getAuthHeader,
  get authProvider() { return getAuthProvider() }
}
