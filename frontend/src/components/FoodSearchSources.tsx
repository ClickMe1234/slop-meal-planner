import { Barcode, Check, Wheat } from 'lucide-react'

export interface FoodSearchSourceSelection { general: boolean; packaged: boolean }

export function FoodSearchSources({ value, onChange, compact = false }: { value: FoodSearchSourceSelection; onChange: (value: FoodSearchSourceSelection) => void; compact?: boolean }) {
  const toggle = (source: keyof FoodSearchSourceSelection) => {
    if (value[source] && Object.values(value).filter(Boolean).length === 1) return
    onChange({ ...value, [source]: !value[source] })
  }
  return <fieldset className={`food-search-sources${compact ? ' food-search-sources--compact' : ''}`}><legend>Search in</legend><button type="button" role="checkbox" aria-checked={value.general} className={value.general ? 'active' : ''} onClick={() => toggle('general')}><Wheat aria-hidden="true"/><span><strong>General</strong><small>USDA</small></span>{value.general && <Check className="source-check" aria-hidden="true"/>}</button><button type="button" role="checkbox" aria-checked={value.packaged} className={value.packaged ? 'active' : ''} onClick={() => toggle('packaged')}><Barcode aria-hidden="true"/><span><strong>Packaged</strong><small>Open Food Facts</small></span>{value.packaged && <Check className="source-check" aria-hidden="true"/>}</button></fieldset>
}
