import type { Nutrition as NutritionType } from '../types'

export function NutritionStrip({ nutrition, compact = false }: { nutrition: NutritionType; compact?: boolean }) {
  const values = [
    ['Calories', `${Math.round(nutrition.calories)}`, 'kcal'],
    ['Protein', `${Math.round(nutrition.protein)}`, 'g'],
    ['Carbs', `${Math.round(nutrition.carbs)}`, 'g'],
    ['Fat', `${Math.round(nutrition.fat)}`, 'g']
  ]
  return <div className={`nutrition-strip ${compact ? 'nutrition-strip--compact' : ''}`}>{values.map(([label, value, unit]) => <div key={label}><span>{label}</span><strong>{value}<small>{unit}</small></strong></div>)}</div>
}

export function NutritionRings({ calories, target, protein, carbs, fat }: { calories: number; target: number; protein: number; carbs: number; fat: number }) {
  const pct = Math.min(100, Math.round(calories / target * 100))
  return <div className="nutrition-summary">
    <div className="calorie-ring" style={{ '--progress': `${pct * 3.6}deg` } as React.CSSProperties}>
      <div><strong>{calories}</strong><span>of {target} kcal</span></div>
    </div>
    <div className="macro-bars">
      <Macro label="Protein" value={protein} target={130} tone="green" />
      <Macro label="Carbs" value={carbs} target={225} tone="warm" />
      <Macro label="Fat" value={fat} target={67} tone="blue" />
    </div>
  </div>
}

function Macro({ label, value, target, tone }: { label: string; value: number; target: number; tone: string }) {
  return <div className="macro-row"><div><span>{label}</span><small>{value} / {target}g</small></div><div className="macro-track"><span className={`macro-fill macro-fill--${tone}`} style={{ width: `${Math.min(100, value / target * 100)}%` }} /></div></div>
}
