import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PantryPage } from './PantryPage'

function renderPantry() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><PantryPage/></QueryClientProvider>)
}

describe('PantryPage batch controls', () => {
  afterEach(() => vi.restoreAllMocks())

  it('selects and deletes multiple available pantry items together', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPantry()

    for (const name of ['Couscous', 'Lentils']) {
      await user.click(screen.getByRole('button', { name: /add item/i }))
      await user.type(screen.getByRole('textbox', { name: 'Ingredient' }), name)
      await user.click(screen.getByRole('button', { name: /add to pantry/i }))
    }

    await user.click(screen.getByRole('button', { name: /select items/i }))
    await user.click(screen.getByRole('checkbox', { name: 'Select Couscous' }))
    await user.click(screen.getByRole('checkbox', { name: 'Select Lentils' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /delete selected/i }))

    expect(screen.queryByText('Couscous')).not.toBeInTheDocument()
    expect(screen.queryByText('Lentils')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /select items/i })).toBeInTheDocument()
  })

  it('does not allow reserved items to be selected', async () => {
    const user = userEvent.setup()
    renderPantry()

    await user.click(screen.getByRole('button', { name: /select items/i }))

    expect(screen.getByRole('checkbox', { name: /Basmati rice cannot be selected/i })).toBeDisabled()
  })
})
