import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api, type BackendPlanDetail } from '../api/client'
import { buildPreservingEditPayload, PlanEditPage } from './PlanEditPage'

const planDetail: BackendPlanDetail = {
  plan: {
    id: 'plan-1',
    name: 'Current week',
    start_date: '2026-07-27',
    end_date: '2026-07-29',
    status: 'accepted',
    diagnostics: [],
    version: 4,
    guest_days: [{ meal_date: '2026-07-27', guest_count: 2, meal_types: ['dinner'] }],
    calorie_boosts: [{ meal_date: '2026-07-27', member_id: 'member-1', calories: 200 }],
  },
  occurrences: [
    {
      id: 'monday-dinner',
      meal_date: '2026-07-27',
      meal_type: 'dinner',
      batch_id: 'batch-a',
      component_slot: 0,
      recipe_id: 'recipe-a',
      recipe_title: 'Harissa chicken',
      batch_servings: 6,
      planned_cook_date: '2026-07-27',
      portions: [{ member_id: 'member-1', servings: 2 }],
    },
    {
      id: 'tuesday-dinner',
      meal_date: '2026-07-28',
      meal_type: 'dinner',
      batch_id: 'batch-a',
      component_slot: 0,
      recipe_id: 'recipe-a',
      recipe_title: 'Harissa chicken',
      batch_servings: 6,
      planned_cook_date: '2026-07-27',
      portions: [{ member_id: 'member-1', servings: 2 }],
    },
    {
      id: 'wednesday-dinner',
      meal_date: '2026-07-29',
      meal_type: 'dinner',
      batch_id: 'batch-b',
      component_slot: 0,
      recipe_id: 'recipe-b',
      recipe_title: 'Miso salmon',
      batch_servings: 2,
      planned_cook_date: '2026-07-29',
      portions: [{ member_id: 'member-1', servings: 2 }],
    },
  ],
}

afterEach(() => vi.restoreAllMocks())

describe('buildPreservingEditPayload', () => {
  it('serialises only week-shape changes without accepting recipe replacements', () => {
    expect(buildPreservingEditPayload(
      planDetail,
      new Set(['2026-07-29']),
      { '2026-07-27': { count: 0, mealTypes: ['dinner'] } },
      { '2026-07-27::member-1': { calories: '350', mealAllocations: [] } },
      new Set(['2026-07-28::dinner']),
    )).toEqual({
      expected_plan_version: 4,
      removed_dates: ['2026-07-29'],
      calorie_boosts: [{
        meal_date: '2026-07-27',
        member_id: 'member-1',
        calories: 350,
        meal_allocations: [],
      }],
      guest_days: [],
      added_cook_days: [{ meal_date: '2026-07-28', meal_type: 'dinner' }],
      ignore_nutrition_tolerances: false,
    })
  })
})

describe('PlanEditPage', () => {
  it('starts a recipe-preserving edit from the week and submits explicit changes', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPlan').mockResolvedValue(planDetail)
    vi.spyOn(api, 'listMembers').mockResolvedValue([
      { id: 'member-1', name: 'Alex', active: true, version: 1 },
    ])
    const edit = vi.spyOn(api, 'editPlanPreservingRecipes').mockResolvedValue({
      ...planDetail,
      plan: { ...planDetail.plan, version: 5 },
    })

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/plan/plan-1/edit']}>
          <Routes>
            <Route path="/plan/:planId/edit" element={<PlanEditPage/>}/>
            <Route path="/week" element={<div>Updated week</div>}/>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Adjust the week, keep the meals' })).toBeInTheDocument()
    expect(screen.getByText('2 recipes pinned')).toBeInTheDocument()

    const monday = screen.getByRole('region', { name: 'Pinned recipes for 2026-07-27' }).closest('.plan-edit-day') as HTMLElement
    await user.click(within(monday).getByRole('button', { name: 'Remove guests' }))
    const calorieBoost = within(monday).getAllByRole('spinbutton')[1]
    await user.clear(calorieBoost)
    await user.type(calorieBoost, '350')

    const tuesday = screen.getByRole('region', { name: 'Pinned recipes for 2026-07-28' }).closest('.plan-edit-day') as HTMLElement
    await user.click(within(tuesday).getByRole('button', { name: 'Add cooking day' }))

    const wednesday = screen.getByRole('region', { name: 'Pinned recipes for 2026-07-29' }).closest('.plan-edit-day') as HTMLElement
    await user.click(within(wednesday).getByRole('button', { name: 'Remove day' }))
    await user.click(screen.getByRole('button', { name: 'Save plan changes' }))

    await waitFor(() => expect(edit).toHaveBeenCalledWith('plan-1', expect.objectContaining({
      expected_plan_version: 4,
      removed_dates: ['2026-07-29'],
      guest_days: [],
      added_cook_days: [{ meal_date: '2026-07-28', meal_type: 'dinner' }],
      calorie_boosts: [expect.objectContaining({ meal_date: '2026-07-27', member_id: 'member-1', calories: 350 })],
    })))
    expect(await screen.findByText('Updated week')).toBeInTheDocument()
  })
})
