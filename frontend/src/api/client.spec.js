import { describe, it, expect, vi, beforeEach } from 'vitest'

// The account/usage route is served by the EXTENSION api, on a DIFFERENT host
// from API_URL. It was once fetched through the core client, which meant it
// 404'd for every user on every deployment -- the route existed and answered
// correctly, just not at the address the browser asked. No backend test can see
// that: only something that plays the role of the browser can. Hence this file.

const created = []
vi.mock('axios', () => {
  const make = (cfg) => {
    const inst = {
      defaults: cfg,
      get: vi.fn((url) => {
        if (typeof url === 'string' && url.includes('/original')) {
          return Promise.resolve({ data: { url: 'https://signed.example/download' } })
        }
        return Promise.resolve({ data: { plan: 'pro', usage: [] } })
      }),
      post: vi.fn(() => Promise.resolve({ data: {} })),
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    }
    created.push(inst)
    return inst
  }
  return { default: { create: vi.fn(make) } }
})

vi.mock('./auth.js', () => ({
  getAuthHeader: () => ({ Authorization: 'Bearer test-token' }),
  getAuthProvider: () => 'cognito',
  login: vi.fn(),
}))

const config = {}
vi.mock('../config.js', () => ({
  getConfig: (key, fallback = '') => (key in config ? config[key] : fallback),
}))

const CORE = 'https://core.example.com/Prod'
const EXTENSION = 'https://extension.example.com/Prod'

describe('account usage client', () => {
  beforeEach(async () => {
    created.length = 0
    for (const k of Object.keys(config)) delete config[k]
    const client = await import('./client.js')
    client._resetClientsForTest()
  })

  it('sends /account/usage to the EXTENSION base url, not the core one', async () => {
    config.API_URL = CORE
    config.ENTERPRISE_API_URL = EXTENSION

    const { getAccountUsage } = await import('./client.js')
    await getAccountUsage()

    // Exactly one instance should have been asked for /account/usage, and its
    // baseURL must be the extension host. This is the regression: against the
    // old code the call went out on the CORE instance and 404'd in production.
    const callers = created.filter((i) => i.get.mock.calls.length > 0)
    expect(callers).toHaveLength(1)
    expect(callers[0].get).toHaveBeenCalledWith('/account/usage')
    expect(callers[0].defaults.baseURL).toBe(EXTENSION)
    expect(callers[0].defaults.baseURL).not.toBe(CORE)
  })

  it('attaches the auth interceptors to the extension client too', async () => {
    config.API_URL = CORE
    config.ENTERPRISE_API_URL = EXTENSION

    const { getAccountUsage } = await import('./client.js')
    await getAccountUsage()

    const caller = created.find((i) => i.get.mock.calls.length > 0)
    // Both request (JWT) and response (401 -> re-login) interceptors, exactly as
    // the core client gets -- the extension client must never drift from it.
    expect(caller.interceptors.request.use).toHaveBeenCalled()
    expect(caller.interceptors.response.use).toHaveBeenCalled()
  })

  it('degrades gracefully when the deployment has no extension api', async () => {
    config.API_URL = CORE
    // ENTERPRISE_API_URL deliberately absent -- a plain core-only install.

    const { getAccountUsage, hasExtensionApi } = await import('./client.js')
    expect(hasExtensionApi()).toBe(false)

    await expect(getAccountUsage()).rejects.toMatchObject({
      isExtensionUnavailable: true,
    })

    // Critically: it must NOT have fallen back to the core client and fired a
    // request that is guaranteed to 404.
    expect(created.every((i) => i.get.mock.calls.length === 0)).toBe(true)
  })

  it('reports the extension api as present when configured', async () => {
    config.API_URL = CORE
    config.ENTERPRISE_API_URL = EXTENSION
    const { hasExtensionApi } = await import('./client.js')
    expect(hasExtensionApi()).toBe(true)
  })
})

describe('getDocumentOriginalUrl', () => {
  beforeEach(async () => {
    created.length = 0
    for (const k of Object.keys(config)) delete config[k]
    const client = await import('./client.js')
    client._resetClientsForTest()
  })

  it('hits the core /original path and returns the presigned url', async () => {
    config.API_URL = CORE
    const { getDocumentOriginalUrl } = await import('./client.js')
    const url = await getDocumentOriginalUrl('doc-1', 'ns-a')

    const caller = created.find((i) => i.get.mock.calls.length > 0)
    expect(caller.defaults.baseURL).toBe(CORE)   // the CORE client, not the extension one
    const [path, cfg] = caller.get.mock.calls[0]
    expect(path).toBe('/api/documents/doc-1/original')
    expect(cfg).toEqual({ params: { namespace: 'ns-a' } })
    expect(url).toBe('https://signed.example/download')
  })

  it('returns null (no broken link) when the original is gone (404)', async () => {
    config.API_URL = CORE
    const { getDocumentOriginalUrl } = await import('./client.js')
    // Make the next GET 404.
    const client = await import('./client.js')
    const inst = created.find(Boolean) || null
    // Force a fresh client whose get rejects with a 404-shaped error.
    client._resetClientsForTest()
    created.length = 0
    const axios = (await import('axios')).default
    axios.create.mockImplementationOnce((cfg) => {
      const i = {
        defaults: cfg,
        get: vi.fn(() => Promise.reject(Object.assign(new Error('nf'), { status: 404 }))),
        post: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
      }
      created.push(i); return i
    })
    const url = await getDocumentOriginalUrl('missing', null)
    expect(url).toBeNull()
  })
})
