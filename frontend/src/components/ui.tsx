import { useEffect, useId, useRef } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
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
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([])
  const choose = (next: T, index?: number) => {
    onChange(next)
    if (index !== undefined) {
      window.requestAnimationFrame(() => buttonRefs.current[index]?.focus())
    }
  }
  const move = (index: number, event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (!options.length) return
    let nextIndex: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % options.length
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (index - 1 + options.length) % options.length
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = options.length - 1
    if (nextIndex === null) return
    event.preventDefault()
    choose(options[nextIndex].value, nextIndex)
  }
  return <div className="segmented" role="radiogroup" aria-label={label} aria-orientation="horizontal">{options.map((option, index) => <button
    key={option.value}
    ref={button => { buttonRefs.current[index] = button }}
    type="button"
    role="radio"
    aria-checked={value === option.value}
    tabIndex={value === option.value ? 0 : -1}
    className={value === option.value ? 'active' : ''}
    onClick={() => choose(option.value, index)}
    onKeyDown={event => move(index, event)}
  >{option.label}</button>)}</div>
}

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * The shared modal surface. Keeping focus and Escape handling here prevents
 * each page-level overlay from drifting into subtly different behaviour.
 */
export function Dialog({ title, onClose, children, wide = false, className = '' }: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
  className?: string
}) {
  const dialogRef = useRef<HTMLElement>(null)
  const titleId = useId()
  const restoreRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    restoreRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    if (!dialog) return
    const first = dialog.querySelector<HTMLElement>('[data-dialog-autofocus], ' + focusableSelector)
    first?.focus()
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
      if (!focusable.length) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const firstFocusable = focusable[0]
      const lastFocusable = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === firstFocusable || !dialog.contains(document.activeElement))) {
        event.preventDefault()
        lastFocusable.focus()
      } else if (!event.shiftKey && (document.activeElement === lastFocusable || !dialog.contains(document.activeElement))) {
        event.preventDefault()
        firstFocusable.focus()
      }
    }
    dialog.addEventListener('keydown', onKeyDown)
    return () => {
      dialog.removeEventListener('keydown', onKeyDown)
      if (restoreRef.current?.isConnected) restoreRef.current.focus()
    }
  }, [onClose])

  return <div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section
      ref={dialogRef}
      className={`card dialog-card ${wide ? 'dialog-card--wide' : ''} ${className}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
    >
      <header>
        <h2 id={titleId}>{title}</h2>
        <button type="button" aria-label="Close" data-dialog-autofocus onClick={onClose}><span aria-hidden="true">×</span></button>
      </header>
      {children}
    </section>
  </div>
}
