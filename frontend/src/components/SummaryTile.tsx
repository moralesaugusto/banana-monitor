import type { ReactNode } from 'react'

/** An icon, a small label and a big number: the summary row at the top of a list page. */
export function SummaryTile({
  icon,
  label,
  value,
  tone = 'neutral',
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  tone?: 'ok' | 'warn' | 'bad' | 'neutral'
}) {
  const toneClasses = {
    ok: 'text-emerald-600 dark:text-emerald-400',
    warn: 'text-amber-600 dark:text-amber-400',
    bad: 'text-red-600 dark:text-red-400',
    neutral: 'text-fg',
  }[tone]
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line text-fg-muted">
        {icon}
      </span>
      <div>
        <div className="text-sm text-fg-muted">{label}</div>
        <div className={`font-mono text-2xl font-medium tabular-nums leading-tight ${toneClasses}`}>{value}</div>
      </div>
    </div>
  )
}
