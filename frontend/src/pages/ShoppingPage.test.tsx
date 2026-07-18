import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ShoppingPage } from './ShoppingPage'


describe('ShoppingPage controls', () => {
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

  it('lets the shopper choose the most useful measurement unit', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage/>)

    const controls = await screen.findByLabelText('Display unit for Greek yoghurt')
    await user.click(within(controls).getByRole('button', { name: 'ml' }))

    expect(screen.getByText('480 ml')).toBeInTheDocument()
    expect(within(controls).getByRole('button', { name: 'ml' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('flags incompatible pantry units and applies an explicit user conversion', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage/>)

    await user.click(await screen.findByRole('button', { name: 'Review pantry' }))
    await user.type(screen.getByRole('spinbutton', { name: /Remove from pantry/ }), '1')
    await user.type(screen.getByRole('spinbutton', { name: /This amount covers/ }), '760')
    await user.click(screen.getByRole('button', { name: 'Use pantry amount' }))

    expect(screen.queryByText('Chickpeas')).not.toBeInTheDocument()
    expect(screen.getByText(/pantry stock adjusted/i)).toBeInTheDocument()
  })

  it('allows the shopper to keep the full purchase without changing pantry', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage/>)

    await user.click(await screen.findByRole('button', { name: 'Review pantry' }))
    await user.click(screen.getByRole('button', { name: 'Buy as listed' }))

    expect(screen.getByText('Chickpeas')).toBeInTheDocument()
    expect(screen.queryByText('Pantry amount needs review')).not.toBeInTheDocument()
  })

  it('lets the shopper confirm a readable pantry match before reviewing units', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage/>)

    expect(await screen.findByText('Possible pantry match')).toBeInTheDocument()
    expect(screen.getByText((_, node) => node?.tagName === 'P'
      && node.textContent === 'Is your pantry item Courgette (4 items) the same ingredient as Courgette on this list?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Yes, match these' }))

    expect(screen.queryByText('Possible pantry match')).not.toBeInTheDocument()
    expect(screen.getByText(/Courgette is now linked for this and future shopping lists/i)).toBeInTheDocument()
    expect(screen.getByText('Decide what this pantry stock covers')).toBeInTheDocument()
  })
})
