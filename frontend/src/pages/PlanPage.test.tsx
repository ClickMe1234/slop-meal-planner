import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { BackendPlanDetail } from '../api/client'
import { PlanPage } from './PlanPage'
import { storeDemoPlan } from './planner'

function renderPlanner() {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan']}><PlanPage/></MemoryRouter></QueryClientProvider>)
}

describe('PlanPage wizard', () => {
  it('moves from dates directly to live household selection without a static Maya profile', async () => {
    const user = userEvent.setup()
    renderPlanner()

    expect(screen.getByRole('heading', { name: 'When are you planning for?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(screen.getByRole('heading', { name: 'Who is eating?' })).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.queryByText('Maya')).not.toBeInTheDocument()
  })

  it('uses controlled member selection and exposes per-meal attendance controls', async () => {
    const user = userEvent.setup()
    renderPlanner()
    await user.click(screen.getByRole('button', { name: /continue/i }))

    const member = screen.getByRole('checkbox', { name: /you/i })
    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(member).toBeChecked()
    await user.click(member)
    expect(member).not.toBeChecked()
    expect(continueButton).toBeDisabled()
    await user.click(member)
    await user.click(continueButton)

    expect(screen.getByRole('heading', { name: 'Who needs each meal?' })).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox', { name: /you needs breakfast/i })).toHaveLength(7)
  })

  it('shows portion-adjusted daily nutrition and lets each day collapse', async () => {
    const plan: BackendPlanDetail = {
      plan: {
        id: 'demo',
        name: 'Demo plan',
        start_date: '2026-07-13',
        end_date: '2026-07-13',
        status: 'ready',
        diagnostics: [],
        version: 1,
      },
      occurrences: [{
        id: 'breakfast',
        meal_date: '2026-07-13',
        meal_type: 'breakfast',
        batch_id: 'breakfast-batch',
        recipe_id: 'oats',
        recipe_title: 'Oats',
        batch_servings: 1.5,
        nutrition_per_serving: { energy_kcal: 400, protein_g: 20, carbohydrate_g: 50, fat_g: 10 },
        portions: [{ member_id: 'demo-you', servings: 1.5 }],
      }],
    }
    storeDemoPlan(plan)
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan?plan=demo']}><PlanPage/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByText('Calories').parentElement).toHaveTextContent('600kcal')
    expect(screen.getByText('Protein').parentElement).toHaveTextContent('30g')
    expect(screen.getByText('Carbs').parentElement).toHaveTextContent('75g')
    expect(screen.getByText('Fat').parentElement).toHaveTextContent('15g')

    const collapse = screen.getByRole('button', { name: 'Collapse 2026-07-13' })
    await user.click(collapse)
    expect(screen.getByRole('button', { name: 'Expand 2026-07-13' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Oats')).not.toBeVisible()
  })

  it('renders empty range days and locks recipe changes after acceptance', () => {
    const plan: BackendPlanDetail = {
      plan: {
        id: 'demo',
        name: 'Accepted plan',
        start_date: '2026-07-13',
        end_date: '2026-07-14',
        status: 'accepted',
        diagnostics: [],
        version: 2,
      },
      occurrences: [{
        id: 'dinner',
        meal_date: '2026-07-13',
        meal_type: 'dinner',
        batch_id: 'dinner-batch',
        recipe_id: 'curry',
        recipe_title: 'Curry',
        batch_servings: 1,
        portions: [{ member_id: 'demo-you', servings: 1 }],
      }],
    }
    storeDemoPlan(plan)
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan?plan=demo']}><PlanPage/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: 'Your accepted plan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open shopping list/i })).toBeInTheDocument()
    expect(screen.getByText('No meals needed')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /customise/i })).not.toBeInTheDocument()
  })
})
