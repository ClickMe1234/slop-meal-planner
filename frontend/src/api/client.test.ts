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

describe('login persistence', () => {
  it('sends the keep-signed-in choice to the server', async () => {
    sessionStorage.setItem('slop-csrf', 'pre-login-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({
      user: { id: 'user-1', username: 'owner', must_change_password: false },
      csrf_token: 'csrf-token',
    }))
    const { api } = await import('./client')

    await api.login('owner', 'password', false)

    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      username: 'owner',
      password: 'password',
      remember_me: false,
    })
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

describe('recipe nutrition preview', () => {
  it('can request a fresh source read', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({
      url: 'https://example.org/recipe',
      publisher: 'Example',
      publisher_nutrition: null,
    }))
    const { api } = await import('./client')

    await api.nutritionPreview('https://example.org/recipe', true)

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/recipe-discovery/nutrition-preview?url=https%3A%2F%2Fexample.org%2Frecipe&refresh=true')
  })

  it('sends transient custom-recipe rows to the side-effect-free preview endpoint', async () => {
    sessionStorage.setItem('slop-csrf', 'current-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({
      complete: false,
      batch_values: {},
      per_serving_values: {},
      issues: [{ code: 'missing_match', message: 'Choose a food record.', client_id: 'beans' }],
      ingredients: [],
    }))
    const { api } = await import('./client')

    await api.previewRecipeNutrition({
      yield_servings: 4,
      ingredients: [{ client_id: 'beans', original_text: '2 cans chickpeas', quantity: 2, unit: 'can', included: true }],
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/recipes/nutrition-preview', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'X-CSRF-Token': 'current-token' }),
      body: JSON.stringify({
        yield_servings: 4,
        ingredients: [{ client_id: 'beans', original_text: '2 cans chickpeas', quantity: 2, unit: 'can', included: true }],
      }),
    }))
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
