import type { ReactNode } from 'react'

export interface SegmentOption<T extends string> {
  value: T
  label: ReactNode
}

/** A row of pills in a tinted tray (the status filter above a table); the active one is a raised pill. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap items-center gap-1 rounded-control bg-canvas p-1">
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`rounded-control px-3 py-1 text-sm transition-colors ${
              active ? 'bg-surface font-medium text-accent-strong shadow-sm' : 'text-fg-muted hover:text-fg'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
