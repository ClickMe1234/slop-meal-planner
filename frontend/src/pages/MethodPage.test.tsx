import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, type BackendMethodView } from '../api/client'
import { MethodPage } from './MethodPage'

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>()
  return { ...original, isDemoMode: false }
})

afterEach(() => vi.restoreAllMocks())

const methodView: BackendMethodView = {
  recipe_id: 'recipe-1',
  recipe_version_id: 'version-1',
  recipe_version_number: 1,
  recipe_version: 1,
  title: 'Tomato supper',
  publisher: 'Good Food',
  source_url: 'https://www.bbcgoodfood.com/recipes/tomato-supper',
  method_status: 'needs_review',
  source_kind: 'publisher',
  source_blocks: [{ id: 'block-1', position: 0, text: 'Fry the tomatoes for 5 minutes.' }],
  method: {
    schema_version: 1,
    annotations: [{ id: 'annotation-1', block_id: 'block-1', start: 8, end: 16, kind: 'ingredient', origin: 'automatic', confidence: .9, accepted: false, ingredient_lineage_id: 'tomato-lineage' }],
    omissions: [],
    stages: [{ id: 'stage-1', title: 'Cook', position: 0 }],
    actions: [{ id: 'action-1', stage_id: 'stage-1', position: 0, text: 'Fry the tomatoes', source_annotation_ids: [], duration_minutes: 5, equipment: ['pan'], confidence: .9 }],
    ingredient_bindings: [{ id: 'binding-1', action_id: 'action-1', ingredient_lineage_id: 'tomato-lineage', portion_mode: 'fraction', portion_value: .5, confidence: .9, accepted: false }],
    edges: [],
  },
  coverage: { total_clauses: 1, represented: 1, omitted: 0, unreviewed: 0 },
  confidence: .9,
  ingredients: [{ id: 'ingredient-1', lineage_id: 'tomato-lineage', name: 'tomatoes', quantity: 4, quantity_text: '4', unit: 'item', display: '4 item tomatoes', optional: false }],
  rendered_blocks: [{ id: 'block-1', position: 0, text: 'Fry the tomatoes for 5 minutes.', segments: [{ kind: 'text', text: 'Fry the ' }, { kind: 'ingredient', text: 'tomatoes', ingredient_lineage_id: 'tomato-lineage', quantity_label: '4 item tomatoes' }, { kind: 'text', text: ' for 5 minutes.' }] }],
  base_servings: 2,
  requested_servings: 4,
  scaling_available: true,
}

const onionSource = 'Fry the onions until soft, then add the stock.'
const onionActionText = onionSource.slice(0, -1)
const onionMethodView: BackendMethodView = {
  ...methodView,
  title: 'Onion supper',
  source_blocks: [{ id: 'block-onion', position: 0, text: onionSource }],
  method: {
    schema_version: 1,
    annotations: [{
      id: 'annotation-action', block_id: 'block-onion', start: 0, end: onionSource.length,
      kind: 'action', origin: 'automatic', confidence: .9, accepted: false,
    }],
    omissions: [],
    stages: [{ id: 'stage-1', title: 'Cook', position: 0 }],
    actions: [{
      id: 'action-1', stage_id: 'stage-1', position: 0, text: onionActionText,
      source_annotation_ids: ['annotation-action'], equipment: [], confidence: .9,
    }],
    ingredient_bindings: [],
    edges: [],
  },
  ingredients: [{
    id: 'ingredient-onion', lineage_id: 'red-onion-lineage', name: 'red onions',
    quantity: 2, quantity_text: '2', unit: 'item', display: '2 item red onions', optional: false,
  }],
  rendered_blocks: [{
    id: 'block-onion', position: 0, text: onionSource,
    segments: [{ kind: 'text', text: onionSource }],
  }],
}

const customMethodView: BackendMethodView = {
  ...onionMethodView,
  title: 'Custom onion supper',
  source_kind: 'custom',
}

function renderMethod(initialEntry = '/recipes/recipe-1/method') {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/recipes/:recipeId/method" element={<MethodPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function mockMethodPage(view: BackendMethodView = methodView) {
  vi.spyOn(api, 'me').mockResolvedValue({
    id: 'user-1', username: 'owner', role: 'owner', must_change_password: false,
    ingredient_locale: 'uk', method_view_preference: 'written', measurement_system: 'source',
    method_tutorial_version_seen: 2,
  })
  vi.spyOn(api, 'getRecipe').mockResolvedValue({
    id: 'recipe-1', title: 'Tomato supper', eligibility: 'planner_ready', source_type: 'url',
    source_url: methodView.source_url, publisher: 'Good Food', version: 1, recipe_version_id: 'version-1',
    version_number: 1, yield_servings: 2, meal_types: ['dinner'], planner_eligible: true,
    planner_warnings: [], ingredients: [],
  })
  vi.spyOn(api, 'getRecipeMethod').mockResolvedValue(view)
}

const unresolvedSource = 'Fry the tomatoes for 5 minutes. Whisk the sauce until smooth.'
const unresolvedText = 'Whisk the sauce until smooth.'
const unresolvedStart = unresolvedSource.indexOf(unresolvedText)
const unreviewedMethodView: BackendMethodView = {
  ...methodView,
  source_blocks: [{ id: 'block-1', position: 0, text: unresolvedSource }],
  method: {
    ...methodView.method,
    annotations: [
      ...methodView.method.annotations,
      { id: 'annotation-unreviewed', block_id: 'block-1', start: unresolvedStart, end: unresolvedStart + unresolvedText.length, kind: 'action', origin: 'automatic', confidence: .48, accepted: false },
    ],
    actions: [
      ...methodView.method.actions,
      { id: 'action-2', stage_id: 'stage-1', position: 1, text: unresolvedText.replace('.', ''), source_annotation_ids: ['annotation-unreviewed'], equipment: [], confidence: .48 },
    ],
  },
  coverage: { total_clauses: 2, represented: 1, omitted: 0, unreviewed: 1 },
  rendered_blocks: [{ id: 'block-1', position: 0, text: unresolvedSource, segments: [{ kind: 'text', text: unresolvedSource }] }],
}

describe('MethodPage', () => {
  it('shows only the written method when the saved view preference is summary', async () => {
    mockMethodPage()
    vi.mocked(api.me).mockResolvedValue({
      id: 'user-1', username: 'owner', role: 'owner', must_change_password: false,
      ingredient_locale: 'uk', method_view_preference: 'summary', measurement_system: 'source',
      method_tutorial_version_seen: 2,
    })

    renderMethod()

    expect(await screen.findByRole('heading', { name: 'Tomato supper' })).toBeInTheDocument()
    expect(screen.getByText('4 item tomatoes')).toBeInTheDocument()
    expect(screen.getByText(/for 5 minutes/)).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Summary' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Cook' })).not.toBeInTheDocument()
  })

  it('saves a complete needs-review method as reviewed without opening the editor', async () => {
    const user = userEvent.setup()
    mockMethodPage()
    let currentView = methodView
    vi.mocked(api.getRecipeMethod).mockImplementation(async () => currentView)
    const reviewedView = { ...methodView, method_status: 'reviewed' as const }
    const save = vi.spyOn(api, 'saveRecipeMethod').mockImplementation(async () => {
      currentView = reviewedView
      return reviewedView
    })

    renderMethod()

    expect(await screen.findByRole('heading', { name: 'Tomato supper' })).toBeInTheDocument()
    const reviewButton = screen.getByRole('button', { name: 'Save' })
    expect(reviewButton).toBeEnabled()
    expect(screen.queryByText('Original written method')).not.toBeInTheDocument()

    await user.click(reviewButton)

    await waitFor(() => expect(save).toHaveBeenCalledWith('recipe-1', expect.objectContaining({
      expected_version: 1,
      mark_reviewed: true,
      source_kind: 'publisher',
    })))
    expect(await screen.findByText('Method saved and reviewed.')).toBeInTheDocument()
    expect(screen.getByText('Reviewed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })

  it('makes each unaccounted clause exact, prominent, and locatable in the editor', async () => {
    const user = userEvent.setup()
    mockMethodPage(unreviewedMethodView)

    renderMethod()

    await screen.findByRole('heading', { name: 'Tomato supper' })
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Edit method' }))

    expect(screen.getByText('1 unaccounted clause')).toBeInTheDocument()
    expect(screen.getByText(/This warning does not block saving the reviewed method/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    const locator = screen.getByRole('button', { name: `Locate unaccounted clause 1: ${unresolvedText}` })
    expect(locator).toHaveTextContent(unresolvedText)
    const sourceSpan = document.querySelector('mark[data-unreviewed-clause="true"]') as HTMLElement
    expect(sourceSpan).toHaveTextContent(unresolvedText)
    expect(sourceSpan).toHaveClass('semantic-mark--unreviewed')

    await user.click(locator)

    expect(sourceSpan).toHaveFocus()
  })

  it('persists written-method notes when reviewing with an unaccounted clause', async () => {
    const user = userEvent.setup()
    let currentView = unreviewedMethodView
    mockMethodPage(currentView)
    vi.spyOn(api, 'updateMe').mockResolvedValue({
      id: 'user-1', username: 'owner', role: 'owner', must_change_password: false,
      ingredient_locale: 'uk', method_view_preference: 'summary', measurement_system: 'source',
      method_tutorial_version_seen: 2,
    })
    vi.mocked(api.getRecipeMethod).mockImplementation(async () => currentView)
    const save = vi.spyOn(api, 'saveRecipeMethod').mockImplementation(async (_recipeId, payload) => {
      currentView = {
        ...currentView,
        recipe_version: 2,
        recipe_version_number: 2,
        method_status: payload.mark_reviewed ? 'reviewed' : 'needs_review',
        method: payload.method,
        household_notes: payload.household_notes,
      }
      return currentView
    })

    renderMethod()

    await screen.findByRole('heading', { name: 'Tomato supper' })
    await user.click(screen.getByRole('button', { name: 'Edit method' }))
    await user.type(screen.getByRole('textbox', { name: 'Household notes' }), 'Use the heavy pan.')
    await user.click(screen.getAllByRole('button', { name: 'Save' }).at(-1)!)

    await waitFor(() => expect(save).toHaveBeenCalledWith('recipe-1', expect.objectContaining({
      mark_reviewed: true,
      household_notes: 'Use the heavy pan.',
      method: expect.objectContaining({ actions: unreviewedMethodView.method.actions }),
    })))
    expect(await screen.findByText('Method saved and reviewed.')).toBeInTheDocument()
    expect(screen.getByText('Use the heavy pan.')).toBeInTheDocument()
  })

  it('links a mismatched ingredient to the exact source word and saves its amount binding', async () => {
    const user = userEvent.setup()
    mockMethodPage(onionMethodView)
    const save = vi.spyOn(api, 'saveRecipeMethod').mockImplementation(async (_recipeId, payload) => ({
      ...onionMethodView,
      recipe_version: 2,
      recipe_version_number: 2,
      method: payload.method,
    }))

    renderMethod()

    await screen.findByRole('heading', { name: 'Onion supper' })
    await user.click(screen.getByRole('button', { name: 'Edit method' }))
    await user.click(screen.getByRole('button', { name: /red onions/i }))
    await user.click(screen.getByRole('button', { name: 'Link red onions to “onions”' }))

    expect(screen.getByText(/Linked red onions to “onions”/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(save).toHaveBeenCalled())

    const payload = save.mock.calls[0]![1]
    const annotation = payload.method.annotations.find(item => item.kind === 'ingredient')
    const binding = payload.method.ingredient_bindings.find(item => item.ingredient_lineage_id === 'red-onion-lineage')
    expect(annotation).toMatchObject({
      block_id: 'block-onion',
      start: onionSource.indexOf('onions'),
      end: onionSource.indexOf('onions') + 'onions'.length,
      ingredient_lineage_id: 'red-onion-lineage',
      origin: 'user',
      accepted: true,
    })
    expect(binding).toMatchObject({
      action_id: 'action-1',
      ingredient_lineage_id: 'red-onion-lineage',
      portion_mode: 'unspecified',
      accepted: true,
    })
    expect(binding?.annotation_id).toBe(annotation?.id)
  })

  it('links an ingredient to custom-method wording without requiring a publisher source', async () => {
    const user = userEvent.setup()
    mockMethodPage(customMethodView)
    const save = vi.spyOn(api, 'saveRecipeMethod').mockImplementation(async (_recipeId, payload) => ({
      ...customMethodView,
      recipe_version: 2,
      recipe_version_number: 2,
      method: payload.method,
    }))

    renderMethod()

    await screen.findByRole('heading', { name: 'Custom onion supper' })
    await user.click(screen.getByRole('button', { name: 'Edit method' }))
    await user.click(screen.getByRole('button', { name: /red onions/i }))
    await user.click(screen.getByRole('button', { name: 'Link red onions to “onions”' }))

    expect(screen.getByText(/Linked red onions to “onions”/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(save).toHaveBeenCalled())

    const payload = save.mock.calls[0]![1]
    expect(payload.source_kind).toBe('custom')
    expect(payload.source_blocks).toEqual([expect.objectContaining({ text: onionSource })])
    expect(payload.method.annotations).toEqual(expect.arrayContaining([
      expect.objectContaining({
        ingredient_lineage_id: 'red-onion-lineage',
        origin: 'user',
        accepted: true,
      }),
    ]))
  })

  it('blocks closing and saving while custom wording is being edited', async () => {
    const user = userEvent.setup()
    mockMethodPage(customMethodView)

    renderMethod()

    await screen.findByRole('heading', { name: 'Custom onion supper' })
    await user.click(screen.getByRole('button', { name: 'Edit method' }))
    await user.click(screen.getByRole('button', { name: 'Edit wording' }))

    expect(screen.getByRole('button', { name: 'Close editor' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('keeps serving edits local until Apply so typing does not refetch or lose focus', async () => {
    const user = userEvent.setup()
    mockMethodPage(methodView)
    const getMethod = vi.mocked(api.getRecipeMethod)

    renderMethod()

    await waitFor(() => expect(getMethod).toHaveBeenCalledTimes(1))
    const input = await screen.findByRole('spinbutton', { name: 'Servings' })
    await user.clear(input)
    await user.type(input, '8')

    expect(input).toHaveValue(8)
    expect(getMethod).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => expect(getMethod).toHaveBeenLastCalledWith('recipe-1', {
      batchId: undefined,
      servings: 8,
    }))
  })

  it('keeps a failed serving request retryable and shows the failure', async () => {
    const user = userEvent.setup()
    mockMethodPage(methodView)
    vi.mocked(api.getRecipeMethod).mockImplementation(async (_recipeId, options) => {
      if (options?.servings === 8) throw new Error('The serving request failed.')
      return methodView
    })

    renderMethod()

    const input = await screen.findByRole('spinbutton', { name: 'Servings' })
    await user.clear(input)
    await user.type(input, '8')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    expect(await screen.findByText('The serving request failed.')).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Servings' })).toHaveValue(8)
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled()
  })

  it('offers to capture the current method for a cooked batch with no historical snapshot', async () => {
    const user = userEvent.setup()
    mockMethodPage()
    const recoveredView: BackendMethodView = {
      ...customMethodView,
      requested_servings: 4,
      batch_context: {
        batch_id: 'batch-1',
        servings: 4,
        planned_cook_date: '2026-08-20',
        cooked_at: '2026-08-20T18:00:00Z',
        occurrences: [{ date: '2026-08-20', meal_type: 'dinner' }],
      },
    }
    const capture = vi.spyOn(api, 'recoverHistoricalRecipeMethod').mockResolvedValue(recoveredView)
    vi.mocked(api.getRecipeMethod).mockRejectedValue(new ApiError(
      409,
      'This cooked batch predates method capture. You can copy the current method onto this batch; its cooked record and batch ingredients will stay unchanged.',
      'HISTORICAL_METHOD_NOT_CAPTURED',
      [{
        kind: 'recover_historical_method',
        label: 'Use current method for this batch',
        recipe_id: 'recipe-1',
        batch_id: 'batch-1',
        suggestion: 'Copy the current method onto this historical batch.',
      }],
    ))

    renderMethod('/recipes/recipe-1/method?batch=batch-1')

    expect(await screen.findByText(/predates method capture/)).toBeInTheDocument()
    const recovery = screen.getByRole('button', { name: 'Use current method for this batch' })
    expect(recovery).toBeEnabled()

    await user.click(recovery)

    await waitFor(() => expect(capture).toHaveBeenCalledWith('recipe-1', 'batch-1'))
    expect(await screen.findByText(/current method was captured for this historical batch/)).toBeInTheDocument()
    expect(screen.getByText('Custom onion supper')).toBeInTheDocument()
  })

  it('shows a recovery failure while the historical method is still unavailable', async () => {
    const user = userEvent.setup()
    mockMethodPage()
    const historicalError = new ApiError(
      409,
      'This cooked batch predates method capture.',
      'HISTORICAL_METHOD_NOT_CAPTURED',
      [{ kind: 'recover_historical_method', label: 'Use current method for this batch', batch_id: 'batch-1' }],
    )
    vi.mocked(api.getRecipeMethod).mockRejectedValue(historicalError)
    vi.spyOn(api, 'recoverHistoricalRecipeMethod').mockRejectedValue(new Error('Save the current recipe method first.'))

    renderMethod('/recipes/recipe-1/method?batch=batch-1')

    await user.click(await screen.findByRole('button', { name: 'Use current method for this batch' }))

    expect(await screen.findByText('Historical method recovery failed')).toBeInTheDocument()
    expect(screen.getByText('Save the current recipe method first.')).toBeInTheDocument()
  })

  it('does not expose cooking-flow controls that cannot affect the written view', async () => {
    const user = userEvent.setup()
    mockMethodPage(onionMethodView)

    renderMethod()

    await screen.findByRole('heading', { name: 'Onion supper' })
    await user.click(screen.getByRole('button', { name: 'Edit method' }))
    expect(screen.queryByRole('textbox', { name: 'Action text' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Split step at cursor' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Stage name' })).not.toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === onionSource)).toBeInTheDocument()
  })
})
