import { type CleanCounts, type CleanTarget, useClean, useCleanCounts } from '../api/maintenance'
import { Card } from '../components/Card'

const ITEMS: { target: CleanTarget; count: Exclude<keyof CleanCounts, 'audit'>; label: string; help: string }[] = [
  { target: 'reports', count: 'reports', label: 'Reports', help: 'Saved network and services reports.' },
  { target: 'events', count: 'events', label: 'Events', help: 'The event timeline.' },
  {
    target: 'alerts',
    count: 'alerts',
    label: 'Alerts',
    help: 'Alert states and their transitions. Rules are kept; a problem still happening raises a fresh alert.',
  },
  { target: 'bus', count: 'bus', label: 'Bus', help: 'Pub/sub messages and deliveries of every AI run.' },
  { target: 'ai-runs', count: 'ai_runs', label: 'AI run history', help: 'Past AI runs with their steps and messages.' },
  { target: 'history', count: 'history', label: 'Metrics history', help: 'Check results, samples and rollups behind the charts.' },
]

/** One button per kind of data that piles up. Each asks for confirmation; bus and AI run history
 * are refused by the server while a run is active. */
export function CleanupCard() {
  const { data: counts } = useCleanCounts()
  const clean = useClean()

  return (
    <Card className="p-4">
      <div className="text-sm font-medium text-fg">Clean up data</div>
      <p className="mt-1 text-xs text-fg-muted">
        Permanently deletes the selected data. Devices, services, networks, integrations, credentials, alert
        rules and settings are not touched.
      </p>
      <div className="mt-3 divide-y divide-line text-sm">
        {ITEMS.map((item) => {
          const count = counts?.[item.count]
          return (
            <div key={item.target} className="flex items-center justify-between gap-4 py-2">
              <div>
                <div className="text-fg">
                  {item.label} <span className="font-mono text-xs text-fg-muted">{count ?? ''}</span>
                </div>
                <div className="text-xs text-fg-muted">{item.help}</div>
              </div>
              <button
                type="button"
                aria-label={`Clean ${item.label}`}
                disabled={clean.isPending || count === 0}
                className="shrink-0 rounded-control border border-red-500/60 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
                onClick={() => {
                  if (window.confirm(`Delete all ${item.label.toLowerCase()}? This cannot be undone.`)) {
                    clean.mutate(item.target)
                  }
                }}
              >
                Clean
              </button>
            </div>
          )
        })}
      </div>
      {clean.isSuccess && <p className="mt-2 text-xs text-fg-muted">Deleted {clean.data.deleted} row(s).</p>}
      {clean.isError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{clean.error.message}</p>}
    </Card>
  )
}
