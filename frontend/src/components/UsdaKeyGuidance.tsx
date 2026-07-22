import { CircleHelp, ExternalLink, KeyRound } from 'lucide-react'
import { Link } from 'react-router-dom'

export const USDA_KEY_SIGNUP_URL = 'https://fdc.nal.usda.gov/api-key-signup.html'

export function UsdaKeyGuidance({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`usda-key-guidance${compact ? ' usda-key-guidance--compact' : ''}`} role="status">
      <KeyRound aria-hidden="true" />
      <div>
        <strong>USDA API key needed</strong>
        <span>A free private key gives ingredient search its own reliable quota.</span>
        <span className="usda-key-actions">
          <a href={USDA_KEY_SIGNUP_URL} target="_blank" rel="noreferrer">
            Get a free key <ExternalLink aria-hidden="true" />
          </a>
          <Link to="/settings/system">Add it in Settings</Link>
        </span>
      </div>
      <span className="integration-help" tabIndex={0} aria-label="Why a USDA API key is needed" data-tooltip="FoodData Central limits its shared demo key. Your private key is encrypted by Slop and is never shown again after saving.">
        <CircleHelp aria-hidden="true" />
      </span>
    </div>
  )
}
