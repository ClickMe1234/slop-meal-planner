import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { BackendPlanDetail } from '../api/client'
import { BatchWeightControl, WeekPage, batchWeightPortions, calorieBoostForDate } from './WeekPage'

function renderWeek() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><WeekPage/></QueryClientProvider>)
}

describe('WeekPage', () => {
  it('starts daily nutrition at zero and adds a recipe when it is marked cooked', async () => {
    const user = userEvent.setup()
    renderWeek()
    const nutrition = screen.getByText('Daily nutrition').closest('.nutrition-card') as HTMLElement

    expect(within(nutrition).getByText('0%')).toBeInTheDocument()
    expect(within(nutrition).getByText('0', { selector: '.calorie-ring strong' })).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Mark recipe cooked' })[0])

    expect(within(nutrition).getByText('19%')).toBeInTheDocument()
    expect(within(nutrition).getByText('386', { selector: '.calorie-ring strong' })).toBeInTheDocument()
    const unmark = screen.getByRole('button', { name: 'Unmark recipe cooked' })
    expect(unmark).toBeEnabled()

    await user.click(unmark)

    expect(within(nutrition).getByText('0%')).toBeInTheDocument()
    expect(within(nutrition).getByText('0', { selector: '.calorie-ring strong' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Mark recipe cooked' })).toHaveLength(4)
  })

  it('links recipes with publisher pages from the meal title', () => {
    renderWeek()
    expect(screen.getByRole('link', { name: /Berry overnight oats/ })).toHaveAttribute('href', 'https://www.allrecipes.com/')
  })

  it('reveals the optional cooked weight control after a recipe is cooked', async () => {
    const user = userEvent.setup()
    renderWeek()

    expect(screen.queryByRole('form', { name: 'Cooked batch weight' })).not.toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Mark recipe cooked' })[0])

    expect(screen.getByRole('form', { name: 'Cooked batch weight' })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Total cooked batch weight' })).toBeInTheDocument()
  })

  it('rounds the editable batch weight to grams per person', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()

    function Harness() {
      const [draft, setDraft] = useState('1000')
      return <BatchWeightControl
        servings={4}
        portions={[
          { memberId: 'alex', name: 'Alex', servings: 1.5 },
          { memberId: 'sam', name: 'Sam', servings: 2 },
        ]}
        savedWeight={1000}
        draft={draft}
        onDraftChange={setDraft}
        onSave={onSave}
        onClear={() => undefined}
      />
    }

    render(<Harness/>)
    expect(screen.getByText('375 g')).toBeInTheDocument()
    expect(screen.getByText('500 g')).toBeInTheDocument()

    const input = screen.getByRole('spinbutton', { name: 'Total cooked batch weight' })
    await user.clear(input)
    await user.type(input, '1003')
    expect(screen.getByText('376 g')).toBeInTheDocument()
    expect(screen.getByText('502 g')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Update' }))
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('reconciles a multi-day batch across household portions, boosts and guests', () => {
    const occurrences = [
      {
        id: 'thursday-dinner', meal_date: '2026-07-23', meal_type: 'dinner', batch_id: 'batch', component_slot: 0,
        recipe_id: 'cod', recipe_title: 'Cod', batch_servings: 12, guest_servings: 4,
        portions: [{ member_id: 'alice', servings: 2 }, { member_id: 'zach', servings: 2 }],
      },
      {
        id: 'friday-dinner', meal_date: '2026-07-24', meal_type: 'dinner', batch_id: 'batch', component_slot: 0,
        recipe_id: 'cod', recipe_title: 'Cod', batch_servings: 12, guest_servings: 0,
        portions: [{ member_id: 'alice', servings: 2 }, { member_id: 'zach', servings: 2 }],
      },
    ] satisfies BackendPlanDetail['occurrences']
    const portions = batchWeightPortions(occurrences, 'batch', [
      { id: 'alice', name: 'Alice' }, { id: 'zach', name: 'Zach' },
    ], 'zach')

    expect(portions.reduce((sum, portion) => sum + portion.servings, 0)).toBe(12)
    expect(portions.find(portion => portion.guest)).toMatchObject({ name: 'Guests', servings: 4 })

    render(<BatchWeightControl servings={12} portions={portions} draft="1200" onDraftChange={() => undefined} onSave={() => undefined} onClear={() => undefined}/>)
    const guestRow = screen.getByText('Guests').closest('.batch-weight__portion') as HTMLElement
    expect(guestRow).toHaveTextContent(/Thu,? 23 Jul · 4 servings/)
    expect(guestRow).toHaveTextContent('400 g')
  })

  it('adds the current member calorie boost to the week-view target', () => {
    const plan = {
      id: 'plan', name: 'Week', start_date: '2026-07-23', end_date: '2026-07-24', status: 'ready' as const,
      diagnostics: [], version: 1,
      calorie_boosts: [{ meal_date: '2026-07-24', member_id: 'zach', calories: '1400' }],
    }
    expect(1750 + calorieBoostForDate(plan, '2026-07-24', 'zach')).toBe(3150)
    expect(calorieBoostForDate(plan, '2026-07-24', 'alice')).toBe(0)
  })
})
