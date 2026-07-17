import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { WeekPage } from './WeekPage'

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
})
