import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, type BackendMethodView } from '../api/client'
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

function renderMethod() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/recipes/recipe-1/method']}>
        <Routes>
          <Route path="/recipes/:recipeId/method" element={<MethodPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MethodPage', () => {
  it('opens in the user default, shows scaled ingredient labels, and remembers a toggle', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'me').mockResolvedValue({
      id: 'user-1', username: 'owner', role: 'owner', must_change_password: false,
      ingredient_locale: 'uk', method_view_preference: 'written', measurement_system: 'source',
      method_tutorial_version_seen: 1,
    })
    vi.spyOn(api, 'getRecipe').mockResolvedValue({
      id: 'recipe-1', title: 'Tomato supper', eligibility: 'planner_ready', source_type: 'url',
      source_url: methodView.source_url, publisher: 'Good Food', version: 1, recipe_version_id: 'version-1',
      version_number: 1, yield_servings: 2, meal_types: ['dinner'], planner_eligible: true,
      planner_warnings: [], ingredients: [],
    })
    vi.spyOn(api, 'getRecipeMethod').mockResolvedValue(methodView)
    const updateMe = vi.spyOn(api, 'updateMe').mockResolvedValue({
      id: 'user-1', username: 'owner', role: 'owner', must_change_password: false,
      ingredient_locale: 'uk', method_view_preference: 'summary', measurement_system: 'source',
      method_tutorial_version_seen: 1,
    })

    renderMethod()

    expect(await screen.findByRole('heading', { name: 'Tomato supper' })).toBeInTheDocument()
    expect(screen.getByText('4 item tomatoes')).toBeInTheDocument()
    expect(screen.getByText(/for 5 minutes/)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'Summary' }))
    await waitFor(() => expect(updateMe).toHaveBeenCalledWith({ method_view_preference: 'summary' }))
    expect(screen.getByRole('heading', { name: 'Cook' })).toBeInTheDocument()
    expect(screen.getAllByText((_, element) => element?.textContent === '2 item tomatoes')).not.toHaveLength(0)
    expect(screen.getByText('Fry the tomatoes')).toBeInTheDocument()
  })
})
