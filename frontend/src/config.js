/**
 * Runtime Configuration Loader
 *
 * Supports two configuration sources:
 * 1. Build-time: VITE_* environment variables (baked into bundle)
 * 2. Runtime: /config.json file (loaded at startup)
 *
 * Runtime config takes precedence, allowing pre-built packages
 * to be configured at deployment time.
 *
 * Expected config.json schema:
 * {
 *   "AUTH_PROVIDER": "none" | "cognito" | "apikey",
 *   "API_URL": string (optional, defaults to same-origin),
 *   "COGNITO_USER_POOL_ID": string (required if AUTH_PROVIDER=cognito),
 *   "COGNITO_CLIENT_ID": string (required if AUTH_PROVIDER=cognito),
 *   "COGNITO_DOMAIN": string (required if AUTH_PROVIDER=cognito),
 *   "COGNITO_REDIRECT_URI": string (optional, defaults to window.location.origin),
 *   "API_KEY": string (required if AUTH_PROVIDER=apikey)
 * }
 */

let runtimeConfig = null
let configPromise = null

/**
 * Load runtime configuration from /config.json
 * Falls back gracefully if file doesn't exist.
 * Uses promise singleton pattern to prevent race conditions.
 */
export function loadConfig() {
  if (configPromise) return configPromise

  configPromise = (async () => {
    try {
      // Timeout after 5 seconds to prevent hanging
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 5000)

      try {
        const response = await fetch('/config.json', { signal: controller.signal })
        if (response.ok) {
          const data = await response.json()
          // Basic structure validation
          if (typeof data === 'object' && data !== null) {
            runtimeConfig = data
            console.debug('Runtime config loaded:', Object.keys(runtimeConfig))
          } else {
            console.warn('Invalid config.json: expected object')
          }
        }
      } finally {
        clearTimeout(timeout)
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        console.warn('Config fetch timed out, using build-time environment')
      } else {
        // Config file doesn't exist or failed to load - use build-time config
        console.debug('No runtime config, using build-time environment')
      }
    }
    return runtimeConfig
  })()

  return configPromise
}

/**
 * Get a configuration value
 * Priority: runtime config > VITE_* env var > default
 */
export function getConfig(key, defaultValue = '') {
  // Runtime config takes precedence
  if (runtimeConfig && Object.prototype.hasOwnProperty.call(runtimeConfig, key)) {
    return runtimeConfig[key]
  }

  // Fall back to build-time VITE_* variable
  const envKey = `VITE_${key}`
  if (import.meta.env[envKey] !== undefined) {
    return import.meta.env[envKey]
  }

  return defaultValue
}

/**
 * Get all config values (for debugging)
 */
export function getAllConfig() {
  return {
    runtime: runtimeConfig,
    buildTime: {
      AUTH_PROVIDER: import.meta.env.VITE_AUTH_PROVIDER,
      API_URL: import.meta.env.VITE_API_URL,
      COGNITO_USER_POOL_ID: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      COGNITO_CLIENT_ID: import.meta.env.VITE_COGNITO_CLIENT_ID,
      COGNITO_DOMAIN: import.meta.env.VITE_COGNITO_DOMAIN,
    }
  }
}
