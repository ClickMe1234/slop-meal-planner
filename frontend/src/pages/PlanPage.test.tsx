import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ApiError, type BackendPlanDetail } from '../api/client'
import { buildRecipeImpactDecks, PlanGenerationError, PlanPage } from './PlanPage'
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

  it('collects exercise calories and guest places on special days', async () => {
    const user = userEvent.setup()
    renderPlanner()
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Number of days' }), { target: { value: '1' } })
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(screen.getByRole('heading', { name: 'Anything different this week?' })).toBeInTheDocument()
    await user.type(screen.getByRole('spinbutton', { name: /you extra calories/i }), '1400')
    const guestInput = screen.getByRole('spinbutton', { name: /guests/i })
    await user.type(guestInput, '2')

    const boostSummary = screen.getByText((_, element) => element?.tagName === 'SMALL' && element.textContent === 'active-day boost')
    const guestSummary = screen.getByText((_, element) => element?.tagName === 'SMALL' && element.textContent === 'guest places')
    expect(boostSummary.parentElement).toHaveTextContent('1active-day boost')
    expect(guestSummary.parentElement).toHaveTextContent('2guest places')
  })

  it('imports pantry items by drag and drop and blocks unavailable must-use ingredients', async () => {
    const user = userEvent.setup()
    renderPlanner()
    const days = screen.getByRole('spinbutton', { name: 'Number of days' })
    fireEvent.change(days, { target: { value: '1' } })
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /continue/i }))
    await user.click(screen.getByRole('button', { name: /import from pantry/i }))

    const dialog = screen.getByRole('dialog', { name: 'Import ingredients from your pantry' })
    const miso = within(dialog).getByText('White miso').closest('.pantry-import-item') as HTMLElement
    const unavailableWarning = 'This pantry ingredient is not used by any saved recipe, so it cannot be marked Must use.'
    expect(within(miso).getByLabelText(unavailableWarning)).toHaveAttribute('data-tooltip', unavailableWarning)
    expect(within(miso).getByRole('button', { name: 'Must' })).toBeDisabled()
    await user.click(within(miso).getByRole('button', { name: 'Prefer' }))
    expect(within(dialog).getByRole('status')).toHaveTextContent('White miso moved to Prefer')

    const spinach = within(dialog).getByText('Spinach').closest('.pantry-import-item') as HTMLElement
    const mustZone = within(dialog).getByText('The finished plan must include these.').closest('.pantry-drop-zone') as HTMLElement
    const transfer = {
      effectAllowed: 'move',
      dropEffect: 'move',
      values: new Map<string, string>(),
      setData(type: string, value: string) { this.values.set(type, value) },
      getData(type: string) { return this.values.get(type) ?? '' },
    }
    fireEvent.dragStart(spinach, { dataTransfer: transfer })
    fireEvent.dragOver(mustZone, { dataTransfer: transfer })
    fireEvent.drop(mustZone, { dataTransfer: transfer })

    expect(within(mustZone).getByText('Spinach')).toBeInTheDocument()
    expect(within(dialog).getByRole('status')).toHaveTextContent('Spinach moved to Must use')

    const chickpeas = within(dialog).getByText('Chickpeas').closest('.pantry-import-item') as HTMLElement
    await user.click(within(chickpeas).getByRole('button', { name: 'Prefer' }))

    await user.click(within(dialog).getByRole('button', { name: 'Done' }))
    await user.type(screen.getByRole('textbox', { name: 'Find an ingredient' }), 'Peanuts')
    await user.click(screen.getByRole('button', { name: 'Exclude' }))

    const favoured = screen.getByLabelText('Favoured recipes deck')
    const excluded = screen.getByLabelText('Excluded recipes deck')
    expect(within(favoured).getByText('Fragrant green vegetable curry')).toBeInTheDocument()
    expect(within(favoured).getByText('Must-use match')).toBeInTheDocument()
    await user.click(within(favoured).getByRole('button', { name: 'Next favoured recipe' }))
    expect(within(favoured).getByText('Salmon with summer greens')).toBeInTheDocument()
    await user.click(within(favoured).getByRole('button', { name: 'Next favoured recipe' }))
    expect(within(favoured).getByText('Harissa chicken with chickpeas')).toBeInTheDocument()
    expect(within(favoured).getByText('Preferred match')).toBeInTheDocument()
    expect(within(excluded).getByText('Apple and peanut butter')).toBeInTheDocument()
    expect(screen.getByText('Not found in a saved recipe: White miso')).toBeInTheDocument()
    expect(screen.getByText('Ingredient-only preview. Meal tags, household rules and nutrition targets still shape the final plan.')).toBeInTheDocument()
  })

  it('keeps excluded recipes out of the favoured deck and orders must-use matches first', () => {
    const catalogue = [
      { id: 'spinach', term: 'spinach', name: 'Spinach', recipes: [{ id: 'both', title: 'Both rules' }, { id: 'must', title: 'Must recipe' }] },
      { id: 'beans', term: 'beans', name: 'Beans', recipes: [{ id: 'both', title: 'Both rules' }, { id: 'prefer', title: 'Preferred recipe' }] },
      { id: 'nuts', term: 'nuts', name: 'Nuts', recipes: [{ id: 'both', title: 'Both rules' }] },
    ]
    const decks = buildRecipeImpactDecks(catalogue, {
      must: [catalogue[0]],
      prefer: [catalogue[1]],
      exclude: [catalogue[2]],
    })

    expect(decks.favoured.map(recipe => recipe.id)).toEqual(['must', 'prefer'])
    expect(decks.favoured.map(recipe => recipe.tier)).toEqual(['must', 'prefer'])
    expect(decks.excluded.map(recipe => recipe.id)).toEqual(['both'])
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
        component_slot: 0,
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
      component_slot: 0,
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

  it('shows batch-wide side controls in the generated daily summary', () => {
    storeDemoPlan({
      plan: {
        id: 'demo',
        name: 'Plan with side',
        start_date: '2026-07-13',
        end_date: '2026-07-13',
        status: 'ready',
        diagnostics: [],
        version: 1,
      },
      occurrences: [
        {
          id: 'dinner', meal_date: '2026-07-13', meal_type: 'dinner', batch_id: 'dinner-batch', component_slot: 0,
          recipe_id: 'curry', recipe_title: 'Curry', batch_servings: 1, portions: [{ member_id: 'demo-you', servings: 0.75 }],
        },
        {
          id: 'dinner-side', meal_date: '2026-07-13', meal_type: 'dinner', batch_id: 'side-batch', parent_batch_id: 'dinner-batch', component_slot: 1,
          recipe_id: 'greens', recipe_title: 'Greens', batch_servings: 0.5, portions: [{ member_id: 'demo-you', servings: 0.5 }],
        },
      ],
    })
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/plan?plan=demo']}><PlanPage/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByText('Side')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add side' })).toHaveAttribute('href', expect.stringContaining('/sides/2/recipes'))
    expect(screen.getByRole('link', { name: 'Replace' })).toHaveAttribute('href', expect.stringContaining('/sides/1/recipes'))
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
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
        component_slot: 0,
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

    for (let step = 0; step < 6; step += 1) {
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
