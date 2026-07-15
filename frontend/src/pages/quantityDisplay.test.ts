import { describe, expect, it } from 'vitest'
import type { BackendPantryItem, BackendShoppingItem } from '../api/client'
import { mapPantryItem } from './PantryPage'
import { mapShoppingItem } from './ShoppingPage'


describe('quantity display mapping', () => {
  it('uses server-formatted shopping quantities instead of raw decimal values', () => {
    const item: BackendShoppingItem = {
      id: 'shopping-item',
      display_name: 'Stock',
      exact_quantity: '1.2310',
      purchase_quantity: '1.2400',
      exact_quantity_display: '1.23 l',
      purchase_quantity_display: '1.24 l',
      unit: 'l',
      category: 'Other',
      checked: false,
      manual: false,
      version: 1,
    }

    expect(mapShoppingItem(item)).toMatchObject({
      buy: '1.24 l',
      exact: '1.23 l required',
    })
  })

  it('uses rounded pantry balance labels while retaining numeric values for filters', () => {
    const item: BackendPantryItem = {
      id: 'pantry-item',
      display_name: 'Stock',
      initial_quantity: '1.2400',
      on_hand_quantity: '1.2400',
      reserved_quantity: '0.3300',
      usable_quantity: '0.9100',
      initial_quantity_display: '1.24 l',
      on_hand_quantity_display: '1.24 l',
      reserved_quantity_display: '0.33 l',
      usable_quantity_display: '0.91 l',
      unit: 'l',
      always_have: false,
      version: 1,
    }

    expect(mapPantryItem(item)).toMatchObject({
      quantity: 1.24,
      reserved: 0.33,
      quantityDisplay: '1.24 l',
      reservedDisplay: '0.33 l',
      usableDisplay: '0.91 l',
    })
  })
})
