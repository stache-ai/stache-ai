/**
 * Authentication Factory
 *
 * Supports multiple auth providers:
 * - 'none': No auth (local dev, air-gapped)
 * - 'cognito': AWS Cognito OAuth2 authorization code + PKCE
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
  const ACCESS_TOKEN_KEY = 'stache_access_token' // legacy: no longer written; only purged in clear()
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
    // No id_token (e.g. the client's scopes dropped 'openid') -> reject rather
    // than store the string "undefined" and report a bogus authenticated state.
    if (!tokens?.id_token) throw new Error('token response missing id_token')
    localStorage.setItem(TOKEN_KEY, tokens.id_token)
    // Track expiry from the id token's own exp claim (its TTL can differ from
    // the access token's expires_in), falling back to expires_in.
    let expiry
    try {
      const exp = JSON.parse(atob(tokens.id_token.split('.')[1])).exp
      expiry = exp ? exp * 1000 : Date.now() + (parseInt(tokens.expires_in || '3600', 10) * 1000)
    } catch {
      expiry = Date.now() + (parseInt(tokens.expires_in || '3600', 10) * 1000)
    }
    localStorage.setItem(EXPIRY_KEY, expiry.toString())
    // The access token is never read (the API authorizer validates the id
    // token), so we don't persist it — smaller localStorage exfil surface.
    // A refresh-token grant response does NOT return a new refresh_token; keep the old one.
    if (tokens.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
  }

  const clear = () => {
    for (const k of [TOKEN_KEY, ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY, EXPIRY_KEY]) {
      localStorage.removeItem(k)
    }
  }

  const tokenEndpoint = async (params) => {
    let resp
    try {
      resp = await fetch(`https://${config.domain}/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ client_id: config.clientId, ...params }).toString(),
        signal: AbortSignal.timeout(10000),
      })
    } catch (e) {
      // Network error / timeout: transient, no HTTP status.
      const err = new Error(`token endpoint request failed: ${e}`)
      err.transient = true
      throw err
    }
    const text = await resp.text()
    if (!resp.ok) {
      let oauthError = null
      try { oauthError = JSON.parse(text).error } catch { /* non-JSON body */ }
      const err = new Error(`token endpoint ${resp.status}: ${text}`)
      err.status = resp.status
      err.oauthError = oauthError            // e.g. 'invalid_grant'
      err.transient = resp.status >= 500     // 5xx is transient; a 4xx is not
      throw err
    }
    return JSON.parse(text)
  }

  const login = async () => {
    if (!isConfigured()) {
      console.error('Cognito not configured. Set VITE_COGNITO_* environment variables.')
      return
    }
    if (!window.crypto?.subtle) {
      // PKCE needs Web Crypto, which is only present in a secure context
      // (https or localhost). Fail loudly instead of an opaque TypeError.
      console.error('PKCE login requires a secure (https) context; window.crypto.subtle is unavailable.')
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
    return true // signals the caller that a redirect was initiated
  }

  const logout = () => {
    // Best-effort refresh-token revocation so a token stolen via XSS can't
    // outlive an explicit logout. Fire-and-forget (keepalive) before we clear.
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (refreshToken && config.domain) {
      try {
        fetch(`https://${config.domain}/oauth2/revoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ token: refreshToken, client_id: config.clientId }).toString(),
          keepalive: true,
        }).catch(() => {})
      } catch { /* ignore */ }
    }
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

  /**
   * Exchange the ?code returned by the Hosted UI (or surface an ?error).
   * Returns true only on a successful token exchange. The caller (router guard)
   * strips the oauth params from the URL via the router — a raw replaceState
   * here is undone by Vue Router's own navigation.
   */
  const handleCallback = async () => {
    const params = new URLSearchParams(window.location.search)
    const oauthError = params.get('error')
    if (oauthError) {
      console.error(`OAuth error from Cognito: ${oauthError} — ${params.get('error_description') || ''}`)
      sessionStorage.removeItem(PKCE_VERIFIER_KEY)
      sessionStorage.removeItem(OAUTH_STATE_KEY)
      return false
    }
    const code = params.get('code')
    if (!code) return false
    const returnedState = params.get('state')
    const expectedState = sessionStorage.getItem(OAUTH_STATE_KEY)
    const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY)
    sessionStorage.removeItem(PKCE_VERIFIER_KEY)
    sessionStorage.removeItem(OAUTH_STATE_KEY)
    // Strict CSRF check: both the verifier AND a matching state must be present.
    if (!verifier || !expectedState || returnedState !== expectedState) {
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

  /**
   * Silent renew via the refresh token. Single-flight: concurrent callers share
   * one in-flight request so N parallel API calls on load don't fire N refreshes
   * (and a late failure can't clear tokens a peer just persisted). Returns true
   * on success.
   */
  let refreshInFlight = null
  const doRefresh = async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (!refreshToken) return false
    try {
      persist(await tokenEndpoint({ grant_type: 'refresh_token', refresh_token: refreshToken }))
      return true
    } catch (e) {
      // Only a hard invalid_grant means the refresh token is truly dead
      // (revoked/expired/rotated) — clear then. A transient network/5xx keeps
      // the (still valid) refresh token so the next attempt can succeed.
      if (e.oauthError === 'invalid_grant') {
        // Cross-tab guard: only clear if the RT we sent is still the stored one.
        // A sibling tab may have rotated/persisted a fresh token meanwhile.
        if (localStorage.getItem(REFRESH_TOKEN_KEY) === refreshToken) {
          console.error('Refresh token rejected (invalid_grant); clearing session', e)
          clear()
        }
      } else {
        console.error('Token refresh failed (transient); keeping session for retry', e)
      }
      return false
    }
  }
  const refresh = () => {
    if (!refreshInFlight) {
      refreshInFlight = doRefresh().finally(() => { refreshInFlight = null })
    }
    return refreshInFlight
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
