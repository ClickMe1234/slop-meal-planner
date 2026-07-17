import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { BatchWeightControl, WeekPage } from './WeekPage'

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
})
