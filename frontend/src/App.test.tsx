import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders recipe discovery with clear nutrition labels', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: /find something delicious/i })).toBeInTheDocument()
    expect(screen.getAllByText(/calculated per serving/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/source estimate · per serving/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /calculate nutrition/i })).toBeInTheDocument()
  })
})
