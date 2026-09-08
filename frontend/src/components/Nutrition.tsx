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

export function NutritionRings({ calories, target, protein, carbs, fat, macroTargets }: { calories: number; target: number; protein: number; carbs: number; fat: number; macroTargets?: { protein: number; carbs: number; fat: number } }) {
  const pct = Math.min(100, Math.round(calories / target * 100))
  return <div className="nutrition-summary">
    <div className="calorie-ring">
      <svg viewBox="0 0 150 150" aria-hidden="true">
        <circle className="calorie-ring__track" cx="75" cy="75" r="66"/>
        <circle className="calorie-ring__progress" cx="75" cy="75" r="66" pathLength="100" style={{ strokeDashoffset: 100 - pct }}/>
      </svg>
      <div aria-live="polite"><strong>{calories}</strong><span>of {target} kcal</span></div>
    </div>
    <div className="macro-bars">
      <Macro label="Protein" value={protein} target={macroTargets?.protein || 130} tone="green" />
      <Macro label="Carbs" value={carbs} target={macroTargets?.carbs || 225} tone="warm" />
      <Macro label="Fat" value={fat} target={macroTargets?.fat || 67} tone="blue" />
    </div>
  </div>
}

function Macro({ label, value, target, tone }: { label: string; value: number; target: number; tone: string }) {
  return <div className="macro-row"><div><span>{label}</span><small>{value} / {target}g</small></div><div className="macro-track"><span className={`macro-fill macro-fill--${tone}`} style={{ width: `${Math.min(100, value / target * 100)}%` }} /></div></div>
}
