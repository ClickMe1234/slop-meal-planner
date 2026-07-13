import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ApiError, type BackendPlanDetail } from '../api/client'
import { PlanGenerationError, PlanPage } from './PlanPage'
import { storeDemoPlan } from './planner'

function renderPlanner() {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan']}><PlanPage/></MemoryRouter></QueryClientProvider>)
}

describe('PlanPage wizard', () => {
  it('groups nutrition failures by day and matching household members', () => {
    const violations = [{ nutrient: 'protein', actual: '119', low: '120', kind: 'minimum' as const, message: 'Protein: 119 g (minimum 120 g after tolerance)' }]
    const error = new ApiError(
      422,
      'The available recipes could not meet every daily nutrition target.',
      'NUTRITION_TARGET_INFEASIBLE',
      [],
      [
        { date: '2026-07-13', member: 'Alice', violations },
        { date: '2026-07-13', member: 'Zach', violations },
      ],
    )

    render(<PlanGenerationError error={error}/>)

    expect(screen.getByText('Some daily targets could not be met')).toBeInTheDocument()
    expect(screen.getByText('Alice & Zach')).toBeInTheDocument()
    expect(screen.getByText('Protein: 119 g (minimum 120 g after tolerance)')).toBeInTheDocument()
    expect(screen.queryByText(/1.3E\+2/)).not.toBeInTheDocument()
  })

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
        batch_servings: 2,
        nutrition_per_serving: { energy_kcal: 400, protein_g: 20, carbohydrate_g: 50, fat_g: 10 },
        portions: [{ member_id: 'demo-you', servings: 1.5 }, { member_id: 'another-member', servings: 0.5 }],
      }],
    }
    storeDemoPlan(plan)
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan?plan=demo']}><PlanPage/></MemoryRouter></QueryClientProvider>)

    expect(screen.getAllByText('Calories')).toHaveLength(2)
    expect(screen.getByText('You').closest('.day-member-nutrition-row')).toHaveTextContent('600kcal')
    expect(screen.getByText('Household member').closest('.day-member-nutrition-row')).toHaveTextContent('200kcal')

    const collapse = screen.getByRole('button', { name: 'Collapse 2026-07-13' })
    await user.click(collapse)
    expect(screen.getByRole('button', { name: 'Expand 2026-07-13' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Oats')).not.toBeVisible()
  })

  it('shows meals in breakfast, lunch, dinner, snack order', () => {
    const meal = (mealType: string): BackendPlanDetail['occurrences'][number] => ({
      id: mealType,
      meal_date: '2026-07-13',
      meal_type: mealType,
      batch_id: `${mealType}-batch`,
      recipe_id: `${mealType}-recipe`,
      recipe_title: `${mealType} recipe`,
      batch_servings: 1,
      portions: [{ member_id: 'demo-you', servings: 1 }],
    })
    storeDemoPlan({
      plan: {
        id: 'demo',
        name: 'Shuffled plan',
        start_date: '2026-07-13',
        end_date: '2026-07-13',
        status: 'ready',
        diagnostics: [],
        version: 1,
      },
      occurrences: [meal('breakfast'), meal('dinner'), meal('lunch'), meal('snack')],
    })

    const { container } = render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan?plan=demo']}><PlanPage/></MemoryRouter></QueryClientProvider>)

    expect([...container.querySelectorAll('.generated-meal > span')].map(element => element.textContent)).toEqual([
      'Breakfast',
      'Lunch',
      'Dinner',
      'Snack',
    ])
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

  it('warns before creating a plan that will replace the current plan', async () => {
    storeDemoPlan({
      plan: {
        id: 'current-plan',
        name: 'Current family plan',
        start_date: '2026-07-13',
        end_date: '2026-07-19',
        status: 'accepted',
        diagnostics: [],
        version: 2,
      },
      occurrences: [],
    })
    const user = userEvent.setup()
    renderPlanner()
    for (let day = 1; day < 7; day += 1) {
      await user.click(screen.getByRole('button', { name: 'Plan one fewer day' }))
    }

    for (let step = 0; step < 5; step += 1) {
      await user.click(screen.getByRole('button', { name: /continue/i }))
    }
    await user.click(screen.getByRole('button', { name: /generate meal plan/i }))

    const dialog = screen.getByRole('dialog', { name: 'Create a new meal plan?' })
    expect(dialog).toHaveTextContent('Current family plan')
    expect(dialog).toHaveTextContent('will be overwritten')
    await user.click(screen.getByRole('button', { name: 'Keep current plan' }))
    expect(dialog).not.toBeInTheDocument()
  })
})
