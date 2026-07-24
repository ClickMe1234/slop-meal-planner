import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { BackendPlanDetail } from '../api/client'
import { BatchWeightControl, WeekPage, calorieBoostForDate, editPlanPath, guestCountForOccurrence, occurrenceWeightPortions } from './WeekPage'

function renderWeek() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><WeekPage/></QueryClientProvider>)
}

describe('WeekPage', () => {
  it('builds a direct edit-workflow link for the current plan', () => {
    expect(editPlanPath('plan with/slash')).toBe('/plan?plan=plan%20with%2Fslash&edit=setup')
  })

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

  it('shows only the selected day and splits guest weight per person', () => {
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
    const plan = {
      id: 'plan', name: 'Week', start_date: '2026-07-23', end_date: '2026-07-24', status: 'ready' as const,
      diagnostics: [], version: 1,
      guest_days: [{ meal_date: '2026-07-23', guest_count: 2, meal_types: ['dinner'] }],
    }
    const portions = occurrenceWeightPortions(occurrences[0], [
      { id: 'alice', name: 'Alice' }, { id: 'zach', name: 'Zach' },
    ], 'zach', guestCountForOccurrence(plan, occurrences[0]))

    expect(portions.reduce((sum, portion) => sum + portion.servings, 0)).toBe(8)
    expect(portions.filter(portion => portion.guest)).toEqual([
      expect.objectContaining({ name: 'Guest 1', servings: 2 }),
      expect.objectContaining({ name: 'Guest 2', servings: 2 }),
    ])
    expect(portions).toHaveLength(4)

    render(<BatchWeightControl servings={12} portions={portions} draft="1200" onDraftChange={() => undefined} onSave={() => undefined} onClear={() => undefined}/>)
    const firstGuestRow = screen.getByText('Guest 1').closest('.batch-weight__portion') as HTMLElement
    const secondGuestRow = screen.getByText('Guest 2').closest('.batch-weight__portion') as HTMLElement
    expect(firstGuestRow).toHaveTextContent('2 servings')
    expect(firstGuestRow).toHaveTextContent('200 g')
    expect(secondGuestRow).toHaveTextContent('200 g')
    expect(screen.queryByText(/Fri 24 Jul/)).not.toBeInTheDocument()
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
