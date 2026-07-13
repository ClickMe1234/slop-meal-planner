import { describe, expect, it } from 'vitest'
import { shoppingAsText } from './offlineShopping'
import type { ShoppingItem } from '../types'

const item = (id: string, category: string, checked = false): ShoppingItem => ({
  id,
  name: `Item ${id}`,
  buy: '2 packs',
  exact: '1.5 packs required',
  category,
  checked,
  updatedAt: 1
})

describe('shoppingAsText', () => {
  it('groups outstanding items and omits completed items', () => {
    const text = shoppingAsText([item('a', 'Cupboard'), item('b', 'Produce'), item('c', 'Cupboard', true)])
    expect(text).toContain('Cupboard')
    expect(text).toContain('□ Item a — 2 packs')
    expect(text).toContain('Produce')
    expect(text).not.toContain('Item c')
  })
})
