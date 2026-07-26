import { beforeEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('API CSRF recovery', () => {
  it('refreshes a stale token and retries a rejected update once', async () => {
    sessionStorage.setItem('slop-csrf', 'stale-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ code: 'CSRF_FAILED', detail: 'The CSRF token is missing or invalid' }, 403))
      .mockResolvedValueOnce(jsonResponse({ csrf_token: 'fresh-token' }))
      .mockResolvedValueOnce(jsonResponse({ ingredient_locale: 'uk' }))
    const { api } = await import('./client')

    await api.updateMe('uk')

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: expect.objectContaining({ 'X-CSRF-Token': 'stale-token' }),
    })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/csrf')
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      headers: expect.objectContaining({ 'X-CSRF-Token': 'fresh-token' }),
    })
    expect(sessionStorage.getItem('slop-csrf')).toBe('fresh-token')
  })

  it('does not retry non-CSRF failures', async () => {
    sessionStorage.setItem('slop-csrf', 'current-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ code: 'VALIDATION_ERROR', detail: 'Invalid locale' }, 422))
    const { api, ApiError } = await import('./client')

    await expect(api.updateMe('uk')).rejects.toEqual(expect.objectContaining({
      constructor: ApiError,
      status: 422,
      code: 'VALIDATION_ERROR',
    }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('saved food library', () => {
  it('loads every page so client-side ingredient searching uses the whole household library', async () => {
    const first = { id: 'food-1', display_name: 'Greek yoghurt' }
    const second = { id: 'food-2', display_name: 'Baked beans' }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ items: [first], total: 2 }))
      .mockResolvedValueOnce(jsonResponse({ items: [second], total: 2 }))
    const { api } = await import('./client')

    await expect(api.listSavedFoods()).resolves.toEqual({ items: [first, second], total: 2 })
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/saved-foods?q=&page=1&page_size=100',
      '/api/v1/saved-foods?q=&page=2&page_size=100',
    ])
  })
})

describe('recipe deletion', () => {
  it('sends a DELETE request for the selected recipe', async () => {
    sessionStorage.setItem('slop-csrf', 'current-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(null, { status: 204 }))
    const { api } = await import('./client')

    await api.deleteRecipe('recipe-123')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/recipes/recipe-123', expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({ 'X-CSRF-Token': 'current-token' }),
    }))
  })
})
