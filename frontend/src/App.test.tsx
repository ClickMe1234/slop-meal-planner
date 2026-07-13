import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders recipe discovery with clear nutrition labels', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: /find something delicious/i })).toBeInTheDocument()
    expect(screen.getAllByText(/nutrition from good food · per serving/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/nutrition from allrecipes · per serving/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /save recipe/i }).length).toBeGreaterThan(0)
  })

  it('opens website filters and lets a source be disabled', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    await user.click(screen.getByRole('button', { name: /recipe filters/i }))
    const goodFood = screen.getByRole('checkbox', { name: /good food/i })
    expect(screen.getByRole('checkbox', { name: /allrecipes/i })).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: /great british chefs/i })).not.toBeInTheDocument()
    expect(goodFood).toBeChecked()
    await user.click(goodFood)
    expect(goodFood).not.toBeChecked()
  })

  it('parks food matching in the import review', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/imports/demo/review']}><App/></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: /harissa chicken with chickpeas/i })).toBeInTheDocument()
    expect(screen.getAllByText(/nutrition from good food/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/food-data match|match foods|fallback calculation/i)).not.toBeInTheDocument()
  })

  it('warns until a custom recipe has a meal type', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes/new']}><App/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByText(/not used for meal planning yet/i)).toBeInTheDocument()
    await user.click(screen.getByText('Select meal types'))
    await user.click(screen.getByRole('checkbox', { name: 'Lunch' }))

    expect(screen.queryByText(/not used for meal planning yet/i)).not.toBeInTheDocument()
    expect(screen.getByText('1 selected')).toBeInTheDocument()
  })
})
