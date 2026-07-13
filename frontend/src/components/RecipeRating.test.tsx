import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RecipeRating } from './RecipeRating'

describe('RecipeRating', () => {
  it('shows the star rating and formatted number of ratings', () => {
    render(<RecipeRating rating={4.5} count={1234}/>)
    expect(screen.getByLabelText('4.5 out of 5 from 1,234 ratings')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
    expect(screen.getByText('(1,234 ratings)')).toBeInTheDocument()
  })

  it('renders nothing when publisher rating data is incomplete', () => {
    const { container } = render(<RecipeRating rating={4.5}/>)
    expect(container).toBeEmptyDOMElement()
  })
})
