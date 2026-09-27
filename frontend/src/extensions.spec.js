import { describe, it, expect, vi, afterEach } from 'vitest'
import { sanitizeNavLinks, loadExtensions } from './extensions.js'

describe('sanitizeNavLinks', () => {
  it('keeps well-formed links and normalizes newTab', () => {
    expect(sanitizeNavLinks([
      { id: 'a', label: ' A ', href: '/a/index.html' },
      { id: 'b', label: 'B', href: 'https://example.com', icon: '🔗', newTab: true }
    ])).toEqual([
      { id: 'a', label: 'A', href: '/a/index.html', icon: '', newTab: false },
      { id: 'b', label: 'B', href: 'https://example.com', icon: '🔗', newTab: true }
    ])
  })

  it('rejects unsafe or malformed hrefs', () => {
    const hrefs = ['javascript:alert(1)', 'data:text/html,x', '//evil.com', 'relative', '', 42]
    expect(sanitizeNavLinks(hrefs.map((href, i) => ({ id: `x${i}`, label: 'X', href })))).toEqual([])
  })

  it('drops entries missing id or label, and duplicate ids', () => {
    expect(sanitizeNavLinks([
      null,
      'str',
      { label: 'No id', href: '/x' },
      { id: 'y', label: '  ', href: '/y' },
      { id: 'z', label: 'First', href: '/z1' },
      { id: 'z', label: 'Second', href: '/z2' }
    ])).toEqual([{ id: 'z', label: 'First', href: '/z1', icon: '', newTab: false }])
  })

  it('returns [] for non-arrays', () => {
    expect(sanitizeNavLinks(undefined)).toEqual([])
    expect(sanitizeNavLinks({ id: 'a' })).toEqual([])
  })
})

describe('loadExtensions', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns sanitized nav links from /extensions.json', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ navLinks: [{ id: 'g', label: 'G', href: '/g/index.html' }] })
    })
    vi.stubGlobal('fetch', fetchMock)
    expect(await loadExtensions()).toEqual({
      navLinks: [{ id: 'g', label: 'G', href: '/g/index.html', icon: '', newTab: false }]
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/extensions.json')
  })

  it('returns no links when the file is missing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    expect(await loadExtensions()).toEqual({ navLinks: [] })
  })

  it('returns no links when the SPA fallback serves HTML', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => { throw new SyntaxError('Unexpected token <') }
    }))
    expect(await loadExtensions()).toEqual({ navLinks: [] })
  })

  it('returns no links on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
    expect(await loadExtensions()).toEqual({ navLinks: [] })
  })
})
