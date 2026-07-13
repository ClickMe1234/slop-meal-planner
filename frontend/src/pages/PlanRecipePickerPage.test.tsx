import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { BackendPlanDetail } from '../api/client'
import { PlanRecipePickerPage } from './PlanRecipePickerPage'
import { readDemoPlan, storeDemoPlan } from './planner'

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
    { id: 'monday-breakfast', meal_date: '2026-07-13', meal_type: 'breakfast', batch_id: 'breakfast-batch', recipe_id: 'overnight-oats', recipe_title: 'Berry overnight oats', batch_servings: 2, portions: [{ member_id: 'demo-you', servings: 1 }] },
    { id: 'tuesday-breakfast', meal_date: '2026-07-14', meal_type: 'breakfast', batch_id: 'breakfast-batch', recipe_id: 'overnight-oats', recipe_title: 'Berry overnight oats', batch_servings: 2, portions: [{ member_id: 'demo-you', servings: 1 }] },
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
})
