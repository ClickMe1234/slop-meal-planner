import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { BackendPlanDetail } from '../api/client'
import { PlanRecipePickerPage } from './PlanRecipePickerPage'
import { readDemoPlan, storeDemoPlan } from './planner'
import { readPlanEditDraft, writePlanEditDraft } from './planEditDraft'

const demoPlan: BackendPlanDetail = {
  plan: {
    id: 'demo',
    name: 'Demo',
    start_date: '2026-07-13',
    end_date: '2026-07-14',
    status: 'ready',
    diagnostics: [],
    version: 1,
  },
  occurrences: [
    { id: 'monday-breakfast', meal_date: '2026-07-13', meal_type: 'breakfast', batch_id: 'breakfast-batch', component_slot: 0, recipe_id: 'overnight-oats', recipe_title: 'Berry overnight oats', batch_servings: 2, portions: [{ member_id: 'demo-you', servings: 1 }] },
    { id: 'tuesday-breakfast', meal_date: '2026-07-14', meal_type: 'breakfast', batch_id: 'breakfast-batch', component_slot: 0, recipe_id: 'overnight-oats', recipe_title: 'Berry overnight oats', batch_servings: 2, portions: [{ member_id: 'demo-you', servings: 1 }] },
  ],
}

beforeEach(() => {
  sessionStorage.clear()
  storeDemoPlan(demoPlan)
})

describe('PlanRecipePickerPage', () => {
  it('shows only recipes tagged for the occurrence meal type and replaces the whole batch', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan/demo/occurrences/monday-breakfast/recipes?mealType=breakfast']}><Routes><Route path="/plan/:planId/occurrences/:occurrenceId/recipes" element={<PlanRecipePickerPage/>}/><Route path="/plan" element={<div>Plan restored</div>}/></Routes></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: 'Choose a different recipe' })).toBeInTheDocument()
    expect(screen.getByText('Spiced shakshuka')).toBeInTheDocument()
    expect(screen.queryByText('Harissa chicken with chickpeas')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Use this recipe' }))
    await waitFor(() => expect(readDemoPlan()?.occurrences.map(item => item.recipe_title)).toEqual(['Spiced shakshuka', 'Spiced shakshuka']))
  })

  it('offers side or snack recipes and adds the choice to every date in the batch', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan/demo/batches/breakfast-batch/sides/1/recipes?mealType=breakfast']}><Routes><Route path="/plan/:planId/batches/:batchId/sides/:componentSlot/recipes" element={<PlanRecipePickerPage/>}/><Route path="/plan" element={<div>Plan restored</div>}/></Routes></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: 'Add side' })).toBeInTheDocument()
    expect(screen.getByText('Lemon garlic greens')).toBeInTheDocument()
    expect(screen.getByText('Apple and peanut butter')).toBeInTheDocument()
    expect(screen.queryByText('Spiced shakshuka')).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Use this recipe' })[0])
    await waitFor(() => {
      const sides = readDemoPlan()?.occurrences.filter(item => item.component_slot === 1) ?? []
      expect(sides).toHaveLength(2)
      expect(sides.map(item => item.recipe_title)).toEqual(['Lemon garlic greens', 'Lemon garlic greens'])
      expect(sides.every(item => item.parent_batch_id === 'breakfast-batch')).toBe(true)
    })
  })

  it('returns a selected new cook-day recipe to an accepted plan edit draft', async () => {
    const user = userEvent.setup()
    storeDemoPlan({
      ...demoPlan,
      plan: { ...demoPlan.plan, status: 'accepted' },
    })
    writePlanEditDraft('demo', {
      planVersion: 1,
      removedDates: [],
      guests: {},
      boosts: {},
      addedCookDays: {},
      removedCookDays: [],
      recipeSwaps: {},
    })
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan/demo/occurrences/tuesday-breakfast/recipes?mealType=breakfast&editMode=addCook']}><Routes><Route path="/plan/:planId/occurrences/:occurrenceId/recipes" element={<PlanRecipePickerPage/>}/><Route path="/plan/:planId/edit" element={<div>Back in editor</div>}/></Routes></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: 'Choose the new cook-day recipe' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use this recipe' }))

    expect(await screen.findByText('Back in editor')).toBeInTheDocument()
    expect(readPlanEditDraft('demo')?.addedCookDays['2026-07-14::breakfast']).toEqual({
      mealDate: '2026-07-14',
      mealType: 'breakfast',
      recipeId: 'shakshuka',
      recipeTitle: 'Spiced shakshuka',
    })
  })

  it('returns an accepted batch recipe swap to the plan edit draft', async () => {
    const user = userEvent.setup()
    storeDemoPlan({
      ...demoPlan,
      plan: { ...demoPlan.plan, status: 'accepted' },
    })
    writePlanEditDraft('demo', {
      planVersion: 1,
      removedDates: [],
      guests: {},
      boosts: {},
      addedCookDays: {},
      removedCookDays: [],
      recipeSwaps: {},
    })
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan/demo/occurrences/monday-breakfast/recipes?mealType=breakfast&editMode=swap']}><Routes><Route path="/plan/:planId/occurrences/:occurrenceId/recipes" element={<PlanRecipePickerPage/>}/><Route path="/plan/:planId/edit" element={<div>Back in editor</div>}/></Routes></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: 'Swap this batch recipe' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use this recipe' }))

    expect(await screen.findByText('Back in editor')).toBeInTheDocument()
    expect(readPlanEditDraft('demo')?.recipeSwaps['breakfast-batch']).toEqual({
      recipeId: 'shakshuka',
      recipeTitle: 'Spiced shakshuka',
    })
  })
})
