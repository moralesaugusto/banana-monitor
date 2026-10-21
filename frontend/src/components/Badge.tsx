import type { ReactNode } from 'react'

export type BadgeTone = 'ok' | 'bad' | 'warn' | 'info' | 'purple' | 'neutral'

const TONE_CLASSES: Record<BadgeTone, string> = {
  ok: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  bad: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  warn: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  info: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300',
  neutral: 'bg-fg-subtle/15 text-fg-muted',
}

/**
 * Shared pill styling for every status/severity/state indicator in the app.
 * StatusBadge, AlertStateBadge, and the event-severity chip on EventsPage
 * all map their own enum onto one of these five tones instead of each
 * inventing its own color classes.
 */
export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}
