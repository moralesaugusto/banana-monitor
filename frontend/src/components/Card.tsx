import type { HTMLAttributes, ReactNode } from 'react'

type CardProps = HTMLAttributes<HTMLDivElement> & { children: ReactNode }

/** The one bordered-surface treatment used for panels, forms, and tiles. */
export function Card({ children, className = '', ...rest }: CardProps) {
  return (
    <div
      className={`rounded-card border border-line bg-surface ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}

export function StatTile({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  tone?: 'ok' | 'bad' | 'neutral'
}) {
  const toneClasses =
    tone === 'bad'
      ? 'text-red-600 dark:text-red-400'
      : tone === 'ok'
        ? 'text-emerald-600 dark:text-emerald-400'
        : 'text-fg'
  return (
    <Card className="px-4 py-3">
      <div className="text-xs font-medium text-fg-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${toneClasses}`}>{value}</div>
    </Card>
  )
}
