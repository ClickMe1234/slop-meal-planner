export function safeExternalUrl(value?: string | null): string | null {
  if (!value || value.length > 4096) return null
  try {
    const parsed = new URL(value)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null
    return parsed.href
  } catch {
    return null
  }
}

export function safeImageUrl(value?: string | null): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value, window.location.origin)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null
    if (parsed.origin === window.location.origin) return parsed.href
    return `${window.location.origin}/api/v1/recipe-discovery/image?url=${encodeURIComponent(parsed.href)}`
  } catch {
    return null
  }
}

export function openExternalUrl(value?: string | null): void {
  const url = safeExternalUrl(value)
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
