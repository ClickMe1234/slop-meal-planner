import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { CheckCircle2, CircleAlert, LoaderCircle, Sparkles } from 'lucide-react'

export function Button({ variant = 'primary', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button className={`button button--${variant} ${className}`} {...props} />
}

export function Card({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...props} />
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'default' | 'green' | 'warm' | 'blue' | 'warning' }) {
  return <span className={`badge badge--${tone === 'default' ? 'neutral' : tone}`}>{children}</span>
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return <div className="progress-wrap" aria-label={label}><div className="progress-bar"><span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>{label && <small>{label}</small>}</div>
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state">{icon}<h3>{title}</h3><p>{description}</p>{action}</div>
}

export function Notice({ tone = 'info', title, children }: { tone?: 'info' | 'success' | 'warning'; title: string; children: ReactNode }) {
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'warning' ? CircleAlert : Sparkles
  return <div className={`notice notice--${tone}`}><Icon size={19} aria-hidden /><div><strong>{title}</strong><div className="notice-copy">{children}</div></div></div>
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return <span className="loading"><LoaderCircle size={18} className="spin" />{label}</span>
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; label: string }) {
  return <div className="segmented" role="radiogroup" aria-label={label}>{options.map(option => <button key={option.value} type="button" role="radio" aria-checked={value === option.value} className={value === option.value ? 'active' : ''} onClick={() => onChange(option.value)}>{option.label}</button>)}</div>
}
