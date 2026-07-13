import { useId } from 'react'
import type { MealKind } from '../types'

export const RECIPE_MEAL_TYPES = [
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'lunch', label: 'Lunch' },
  { value: 'dinner', label: 'Dinner' },
  { value: 'snack', label: 'Snack' },
  { value: 'side', label: 'Side' },
] as const

export type RecipeMealType = typeof RECIPE_MEAL_TYPES[number]['value']

const VALID_MEAL_TYPES = new Set<string>(RECIPE_MEAL_TYPES.map(option => option.value))

export function normaliseRecipeMealTypes(values: readonly string[] | null | undefined): RecipeMealType[] {
  return Array.from(new Set(
    (values ?? [])
      .map(value => value.trim().toLowerCase())
      .filter((value): value is RecipeMealType => VALID_MEAL_TYPES.has(value)),
  ))
}

export function mealKindLabels(values: readonly string[] | null | undefined): MealKind[] {
  const selected = new Set(normaliseRecipeMealTypes(values))
  return RECIPE_MEAL_TYPES
    .filter(option => selected.has(option.value))
    .map(option => option.label)
}

export function MealTypePicker({
  value,
  onChange,
  label = 'Meal types',
  disabled = false,
}: {
  value: RecipeMealType[]
  onChange: (value: RecipeMealType[]) => void
  label?: string
  disabled?: boolean
}) {
  const labelId = useId()
  const selected = new Set(value)
  const summary = RECIPE_MEAL_TYPES
    .filter(option => selected.has(option.value))
    .map(option => option.label)
    .join(', ')

  const toggle = (mealType: RecipeMealType, checked: boolean) => {
    const next = checked
      ? normaliseRecipeMealTypes([...value, mealType])
      : value.filter(item => item !== mealType)
    onChange(next)
  }

  return <div className="meal-type-picker">
    <span className="meal-type-picker__label" id={labelId}>{label}</span>
    <details>
      <summary aria-labelledby={labelId} aria-disabled={disabled} onClick={event => disabled && event.preventDefault()}>
        <span>{summary || 'Select meal types'}</span>
        <small>{value.length ? `${value.length} selected` : 'None selected'}</small>
      </summary>
      <fieldset aria-labelledby={labelId} disabled={disabled}>
        {RECIPE_MEAL_TYPES.map(option => <label className="check-label" key={option.value}>
          <input
            type="checkbox"
            checked={selected.has(option.value)}
            onChange={event => toggle(option.value, event.target.checked)}
          />
          {option.label}
        </label>)}
      </fieldset>
    </details>
  </div>
}
