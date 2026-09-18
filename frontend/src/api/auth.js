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
 * Cognito OAuth2 provider — authorization code + PKCE.
 *
 * Replaces the legacy implicit flow (response_type=token): PKCE issues a
 * refresh token, so a session can be silently renewed instead of full-redirecting
 * to the Hosted UI every time the id token expires (the old flow's login loop).
 * Public client — no secret is sent (the code_verifier is the proof).
 */
function createCognitoProvider() {
  const config = {
    region: import.meta.env.VITE_AWS_REGION || 'us-east-1',
    userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || '',
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '',
    domain: import.meta.env.VITE_COGNITO_DOMAIN || '',
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI || window.location.origin,
    scope: import.meta.env.VITE_COGNITO_SCOPE || 'email openid profile',
  }

  const TOKEN_KEY = 'stache_id_token'
  const ACCESS_TOKEN_KEY = 'stache_access_token'
  const REFRESH_TOKEN_KEY = 'stache_refresh_token'
  const EXPIRY_KEY = 'stache_token_expiry'
  const PKCE_VERIFIER_KEY = 'stache_pkce_verifier'
  const OAUTH_STATE_KEY = 'stache_oauth_state'

  const isConfigured = () => !!(config.domain && config.clientId)

  const isAuthenticated = () => {
    const token = localStorage.getItem(TOKEN_KEY)
    const expiry = localStorage.getItem(EXPIRY_KEY)
    if (!token || !expiry) return false
    // Valid if more than 5 minutes of life remains.
    return Date.now() < (parseInt(expiry, 10) - 5 * 60 * 1000)
  }

  const canRefresh = () => !!localStorage.getItem(REFRESH_TOKEN_KEY)

  const getToken = () => {
    if (!isAuthenticated()) return null
    return localStorage.getItem(TOKEN_KEY)
  }

  const getUser = () => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return null
    try {
      const decoded = JSON.parse(atob(token.split('.')[1]))
      return { email: decoded.email, sub: decoded.sub, name: decoded.name || decoded.email }
    } catch {
      return null
    }
  }

  // --- PKCE helpers (require a secure context; staging-app is https) ---
  const base64url = (bytes) => {
    let s = ''
    for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b)
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  }
  const randomString = () => base64url(crypto.getRandomValues(new Uint8Array(48)))
  const sha256 = async (str) =>
    base64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str)))

  const persist = (tokens) => {
    const expiry = Date.now() + (parseInt(tokens.expires_in || '3600', 10) * 1000)
    localStorage.setItem(TOKEN_KEY, tokens.id_token)
    if (tokens.access_token) localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
    localStorage.setItem(EXPIRY_KEY, expiry.toString())
    // A refresh-token grant response does NOT return a new refresh_token; keep the old one.
    if (tokens.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
  }

  const clear = () => {
    for (const k of [TOKEN_KEY, ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY, EXPIRY_KEY]) {
      localStorage.removeItem(k)
    }
  }

  const tokenEndpoint = async (params) => {
    const resp = await fetch(`https://${config.domain}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ client_id: config.clientId, ...params }).toString(),
    })
    if (!resp.ok) throw new Error(`token endpoint ${resp.status}: ${await resp.text()}`)
    return resp.json()
  }

  const login = async () => {
    if (!isConfigured()) {
      console.error('Cognito not configured. Set VITE_COGNITO_* environment variables.')
      return
    }
    const verifier = randomString()
    const state = randomString()
    sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier)
    sessionStorage.setItem(OAUTH_STATE_KEY, state)
    const url = new URL(`https://${config.domain}/oauth2/authorize`)
    url.searchParams.set('client_id', config.clientId)
    url.searchParams.set('response_type', 'code')
    url.searchParams.set('scope', config.scope)
    url.searchParams.set('redirect_uri', config.redirectUri)
    url.searchParams.set('code_challenge', await sha256(verifier))
    url.searchParams.set('code_challenge_method', 'S256')
    url.searchParams.set('state', state)
    window.location.href = url.toString()
  }

  const logout = () => {
    clear()
    if (!isConfigured()) {
      window.location.reload()
      return
    }
    const url = new URL(`https://${config.domain}/logout`)
    url.searchParams.set('client_id', config.clientId)
    url.searchParams.set('logout_uri', config.redirectUri)
    window.location.href = url.toString()
  }

  const stripQuery = () =>
    window.history.replaceState(null, '', window.location.pathname)

  /** Exchange the ?code returned by the Hosted UI. Returns true if it consumed a code. */
  const handleCallback = async () => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) return false
    const returnedState = params.get('state')
    const expectedState = sessionStorage.getItem(OAUTH_STATE_KEY)
    const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY)
    // Always clear the URL so a stale code can't be replayed on refresh.
    stripQuery()
    sessionStorage.removeItem(PKCE_VERIFIER_KEY)
    sessionStorage.removeItem(OAUTH_STATE_KEY)
    if (!verifier || (expectedState && returnedState !== expectedState)) {
      console.error('OAuth callback state/verifier mismatch; ignoring code')
      return false
    }
    try {
      persist(await tokenEndpoint({
        grant_type: 'authorization_code',
        code,
        redirect_uri: config.redirectUri,
        code_verifier: verifier,
      }))
      return true
    } catch (e) {
      console.error('Token exchange failed', e)
      return false
    }
  }

  /** Silent renew via the refresh token. Returns true on success. */
  const refresh = async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (!refreshToken) return false
    try {
      persist(await tokenEndpoint({ grant_type: 'refresh_token', refresh_token: refreshToken }))
      return true
    } catch (e) {
      console.error('Token refresh failed', e)
      clear()
      return false
    }
  }

  const getAuthHeader = () => {
    const token = getToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  return {
    isConfigured,
    isAuthenticated,
    canRefresh,
    getToken,
    getUser,
    login,
    logout,
    handleCallback,
    refresh,
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
export const canRefresh = () => auth.canRefresh?.() ?? false
export const getToken = () => auth.getToken()
export const getUser = () => auth.getUser()
export const login = () => auth.login()
export const logout = () => auth.logout()
export const handleCallback = () => auth.handleCallback()
export const refresh = () => auth.refresh?.() ?? Promise.resolve(false)
export const getAuthHeader = () => auth.getAuthHeader()
export const authProvider = AUTH_PROVIDER

export default auth
