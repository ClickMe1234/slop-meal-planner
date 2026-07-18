import { describe, expect, it } from 'vitest'
import type { PantryItem } from '../types'
import { sortPantryItems, stockLevel } from './PantryPage'

const pantry = (name: string, initialQuantity: number, quantity: number, reserved = 0): PantryItem => ({
  id: name,
  name,
  initialQuantity,
  quantity,
  reserved,
  unit: 'g',
  category: 'Pantry',
})

describe('pantry sorting', () => {
  const items = [
    pantry('Rice', 1000, 800),
    pantry('Beans', 400, 200, 100),
    pantry('Apples', 10, 6),
  ]

  it('sorts alphabetically', () => {
    expect(sortPantryItems(items, 'alphabetical').map(item => item.name)).toEqual(['Apples', 'Beans', 'Rice'])
  })

  it('sorts comparable stock percentages in either direction', () => {
    expect(stockLevel(items[1])).toBe(.25)
    expect(sortPantryItems(items, 'stock-low').map(item => item.name)).toEqual(['Beans', 'Apples', 'Rice'])
    expect(sortPantryItems(items, 'stock-high').map(item => item.name)).toEqual(['Rice', 'Apples', 'Beans'])
  })

  it('does not mutate the query result', () => {
    sortPantryItems(items, 'alphabetical')
    expect(items.map(item => item.name)).toEqual(['Rice', 'Beans', 'Apples'])
  })
})
