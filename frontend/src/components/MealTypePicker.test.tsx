import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MealTypePicker, normaliseRecipeMealTypes, type RecipeMealType } from './MealTypePicker'

function PickerHarness() {
  const [value, setValue] = useState<RecipeMealType[]>([])
  return <MealTypePicker value={value} onChange={setValue}/>
}

describe('MealTypePicker', () => {
  it('allows multiple meal types to be selected', async () => {
    const user = userEvent.setup()
    render(<PickerHarness/>)

    await user.click(screen.getByText('Select meal types'))
    await user.click(screen.getByRole('checkbox', { name: 'Breakfast' }))
    await user.click(screen.getByRole('checkbox', { name: 'Dinner' }))

    expect(screen.getByRole('checkbox', { name: 'Breakfast' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Dinner' })).toBeChecked()
    expect(screen.getByText('Breakfast, Dinner')).toBeInTheDocument()
    expect(screen.getByText('2 selected')).toBeInTheDocument()
  })

  it('normalises, deduplicates and rejects unsupported values', () => {
    expect(normaliseRecipeMealTypes(['Dinner', 'dinner', ' brunch ', 'SNACK'])).toEqual(['dinner', 'snack'])
  })
})
