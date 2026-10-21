import { useAuditLog, useCleanAudit } from '../api/maintenance'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

/** Every successful change made through the API: when, by whom, which request. Request bodies are
 * never recorded. Cleaning it is separate from the other clean-up actions on the About page. */
export function AuditPage() {
  const { data: entries, isLoading } = useAuditLog()
  const clean = useCleanAudit()

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Changes made through the web interface and API: who, when and which request. Request contents are not stored."
      />

      <div className="mt-6 flex flex-col gap-4">
        <Card className="flex items-center justify-between gap-4 p-4">
          <p className="text-xs text-fg-muted">The most recent 500 changes are shown, newest first.</p>
          <button
            type="button"
            disabled={clean.isPending || entries?.length === 0}
            className="shrink-0 rounded-control border border-red-500/60 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
            onClick={() => {
              if (window.confirm('Delete the whole audit log? This cannot be undone.')) clean.mutate()
            }}
          >
            Clean audit log
          </button>
        </Card>

        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">User</th>
                <th className="px-4 py-2.5 font-medium">Action</th>
                <th className="px-4 py-2.5 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    Loading…
                  </td>
                </tr>
              )}
              {entries?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    No changes recorded.
                  </td>
                </tr>
              )}
              {entries?.map((entry) => (
                <tr key={entry.id} className="border-b border-line last:border-b-0">
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{new Date(entry.ts).toLocaleString()}</td>
                  <td className="px-4 py-2.5">{entry.actor}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">
                    <span className="font-semibold">{entry.method}</span> {entry.path}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone="ok">{entry.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
