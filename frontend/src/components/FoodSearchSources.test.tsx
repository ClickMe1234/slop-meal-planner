import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { FoodSearchSources, type FoodSearchSourceSelection } from './FoodSearchSources'

function Harness() {
  const [value, setValue] = useState<FoodSearchSourceSelection>({ general: true, packaged: true })
  return <FoodSearchSources value={value} onChange={setValue}/>
}

describe('FoodSearchSources', () => {
  it('allows either source or both, but never neither', async () => {
    const user = userEvent.setup()
    render(<Harness/>)
    const general = screen.getByRole('checkbox', { name: /general usda/i })
    const packaged = screen.getByRole('checkbox', { name: /packaged open food facts/i })
    expect(general).toBeChecked()
    expect(packaged).toBeChecked()
    await user.click(packaged)
    expect(packaged).not.toBeChecked()
    await user.click(general)
    expect(general).toBeChecked()
    await user.click(packaged)
    await user.click(general)
    expect(general).not.toBeChecked()
    expect(packaged).toBeChecked()
  })
})
