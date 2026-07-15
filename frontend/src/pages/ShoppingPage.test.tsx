import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ShoppingPage } from './ShoppingPage'


describe('ShoppingPage ingredient names', () => {
  beforeEach(() => localStorage.clear())

  it('lets a shopper edit an ingredient name inline', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage/>)

    await user.click(await screen.findByRole('button', { name: 'Edit Chicken thighs' }))
    const input = screen.getByRole('textbox', { name: 'Ingredient name' })
    await user.clear(input)
    await user.type(input, 'Chicken thigh fillets')
    await user.click(screen.getByRole('button', { name: /save/i }))

    expect(screen.getByText('Chicken thigh fillets')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Ingredient name' })).not.toBeInTheDocument()
  })
})
