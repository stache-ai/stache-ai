/**
 * Frontend Extensions Loader
 *
 * Optional /extensions.json lets separately deployed add-ons contribute UI
 * (currently nav links) without the core app knowing about them. It is a
 * separate file from /config.json because the core deploy rewrites config.json
 * on every run; add-ons own extensions.json and upsert their entries by id.
 *
 * Expected schema:
 * {
 *   "navLinks": [
 *     { "id": string, "label": string, "href": string,
 *       "icon": string (optional), "newTab": boolean (optional) }
 *   ]
 * }
 *
 * Links render under a "More" dropdown in the header.
 *
 * A missing or malformed file yields no extensions.
 */

const SAFE_HREF = /^(\/(?!\/)|https?:\/\/)/i

/**
 * Keep only well-formed nav links with a same-origin path or http(s) URL
 * (rejects javascript:, data:, protocol-relative, etc.). First id wins.
 */
export function sanitizeNavLinks(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  const links = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const { id, label, href, icon, newTab } = item
    if (typeof id !== 'string' || !id || seen.has(id)) continue
    if (typeof label !== 'string' || !label.trim()) continue
    if (typeof href !== 'string' || !SAFE_HREF.test(href)) continue
    seen.add(id)
    links.push({
      id,
      label: label.trim(),
      href,
      icon: typeof icon === 'string' ? icon.slice(0, 8) : '',
      newTab: newTab === true
    })
  }
  return links
}

/**
 * Fetch /extensions.json. Never throws.
 */
export async function loadExtensions() {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch('/extensions.json', {
      signal: controller.signal,
      cache: 'no-cache'
    })
    if (!response.ok) return { navLinks: [] }
    const data = await response.json()
    if (typeof data !== 'object' || data === null) return { navLinks: [] }
    return { navLinks: sanitizeNavLinks(data.navLinks) }
  } catch {
    // No extensions deployed (or the SPA fallback served index.html)
    return { navLinks: [] }
  } finally {
    clearTimeout(timeout)
  }
}
