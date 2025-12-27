/**
 * Authentication Factory
 *
 * Supports multiple auth providers:
 * - 'none': No auth (local dev, air-gapped)
 * - 'cognito': AWS Cognito OAuth2 implicit flow
 * - 'apikey': Static API key (simple deployments)
 *
 * Configure via VITE_AUTH_PROVIDER environment variable.
 */

// Auth provider from environment (default: none for local dev)
const AUTH_PROVIDER = import.meta.env.VITE_AUTH_PROVIDER || 'none'

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
  const API_KEY = import.meta.env.VITE_API_KEY || localStorage.getItem('stache_api_key') || ''

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
    region: import.meta.env.VITE_AWS_REGION || 'us-east-1',
    userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || '',
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '',
    domain: import.meta.env.VITE_COGNITO_DOMAIN || '',
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI || window.location.origin,
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
      console.error('Cognito not configured. Set VITE_COGNITO_* environment variables.')
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
  switch (AUTH_PROVIDER.toLowerCase()) {
    case 'cognito':
      return createCognitoProvider()
    case 'apikey':
      return createApiKeyProvider()
    case 'none':
    default:
      return noAuthProvider
  }
}

// Export singleton instance
const auth = createAuthProvider()

// Named exports for convenience
export const isConfigured = () => auth.isConfigured()
export const isAuthenticated = () => auth.isAuthenticated()
export const getToken = () => auth.getToken()
export const getUser = () => auth.getUser()
export const login = () => auth.login()
export const logout = () => auth.logout()
export const handleCallback = () => auth.handleCallback()
export const getAuthHeader = () => auth.getAuthHeader()
export const authProvider = AUTH_PROVIDER

export default auth
