import { describe, expect, it, vi } from 'vitest'
import { openExternalUrl, safeExternalUrl, safeImageUrl } from './safeUrls'

describe('safe URL handling', () => {
  it('accepts credential-free HTTP links and rejects active schemes', () => {
    expect(safeExternalUrl('https://example.com/recipe')).toBe('https://example.com/recipe')
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeExternalUrl('data:text/html,unsafe')).toBeNull()
    expect(safeExternalUrl('https://user:password@example.com/')).toBeNull()
  })

  it('renders external images through the same-origin proxy', () => {
    expect(safeImageUrl('/assets/recipe.png')).toBe(`${window.location.origin}/assets/recipe.png`)
    expect(safeImageUrl('https://images.example/recipe.jpg')).toBe(
      `${window.location.origin}/api/v1/recipe-discovery/image?url=${encodeURIComponent('https://images.example/recipe.jpg')}`,
    )
    expect(safeImageUrl('https://user:password@images.example/recipe.jpg')).toBeNull()
    expect(safeImageUrl('data:image/png;base64,unsafe')).toBeNull()
  })

  it('opens external pages without an opener', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openExternalUrl('https://example.com/recipe')
    expect(open).toHaveBeenCalledWith(
      'https://example.com/recipe',
      '_blank',
      'noopener,noreferrer',
    )
    openExternalUrl('javascript:alert(1)')
    expect(open).toHaveBeenCalledTimes(1)
  })
})
