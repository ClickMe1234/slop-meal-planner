import { Star } from 'lucide-react'

export function RecipeRating({ rating, count }: { rating?: number; count?: number }) {
  if (rating == null || count == null) return null
  const label = `${rating.toFixed(1)} out of 5 from ${count.toLocaleString()} ${count === 1 ? 'rating' : 'ratings'}`
  return <span className="recipe-rating" aria-label={label} title={label}>
    <Star size={15} fill="currentColor" aria-hidden="true"/>
    <strong>{rating.toFixed(1)}</strong>
    <span>({count.toLocaleString()} {count === 1 ? 'rating' : 'ratings'})</span>
  </span>
}
