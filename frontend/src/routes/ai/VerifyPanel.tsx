import type { VerifyResult, VerifyStatus } from '../../api/aiMode'
import { Card } from '../../components/Card'

const STYLE: Record<VerifyStatus, { label: string; badge: string }> = {
  ok: { label: 'OK', badge: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' },
  info: { label: 'Note', badge: 'bg-sky-500/15 text-sky-700 dark:text-sky-300' },
  warn: { label: 'Warning', badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300' },
  fail: { label: 'Problem', badge: 'bg-red-500/15 text-red-700 dark:text-red-300' },
}

function verdict(result: VerifyResult): string {
  const problems = result.checks.filter((c) => c.status === 'fail').length
  const warnings = result.checks.filter((c) => c.status === 'warn').length
  if (problems > 0) return `${problems} problem${problems === 1 ? '' : 's'} to fix`
  return warnings > 0 ? `Ready, with ${warnings} warning${warnings === 1 ? '' : 's'}` : 'Ready'
}

/** The checklist Verify produces: what is fine, what to look at, and what will not work. */
export function VerifyPanel({
  result,
  pending,
  error,
  title = 'Verification',
  idle = "Verify checks the tools, that the Ollama host answers and has the model, that the model replies in time, who receives this agent's results, and that each inspection tool has something to inspect.",
}: {
  result: VerifyResult | null
  pending: boolean
  error: string | null
  title?: string
  idle?: string
}) {
  return (
    <Card className="p-4">
      <section aria-label={title}>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{title}</h2>
        {pending && <p className="mt-3 text-sm text-fg-muted">Checking…</p>}
        {error && !pending && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
        {!result && !pending && !error && (
          <p className="mt-3 text-sm text-fg-muted">{idle}</p>
        )}
        {result && !pending && (
          <>
            <p
              className={`mt-3 text-sm font-medium ${result.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-600 dark:text-red-400'}`}
            >
              {verdict(result)}
            </p>
            <ul className="mt-3 flex flex-col gap-3">
              {result.checks.map((check) => (
                <li key={check.id} className="flex items-start gap-2 text-sm">
                  <span className={`mt-0.5 w-16 shrink-0 rounded-full px-2 py-0.5 text-center text-xs font-medium ${STYLE[check.status].badge}`}>
                    {STYLE[check.status].label}
                  </span>
                  <span className="min-w-0">
                    <span className="block">{check.title}</span>
                    {check.detail && <span className="block break-words text-xs text-fg-muted">{check.detail}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </Card>
  )
}
