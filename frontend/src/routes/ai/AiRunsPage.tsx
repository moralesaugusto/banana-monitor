import { Link } from 'react-router-dom'
import { useAiRuns } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { formatDuration } from '../../lib/format'

function duration(startedAt: string, finishedAt: string | null): string {
  if (finishedAt == null) return 'running'
  return formatDuration(new Date(finishedAt).getTime() - new Date(startedAt).getTime())
}

export function AiRunsPage() {
  const { data: runs, isLoading } = useAiRuns()
  return (
    <div>
      <PageHeader title="Run history" description="Every AI Mode run is kept with its full trace so you can review and learn from it. Open a run for the full step-by-step trace; a failed or odd-looking run's reason is shown here too, so you don't have to open every one to triage." />
      <div className="mt-6">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Run</th>
                <th className="px-4 py-2.5 font-medium">Started</th>
                <th className="px-4 py-2.5 font-medium">Duration</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Entry agent</th>
                <th className="px-4 py-2.5 font-medium">Model</th>
                <th className="px-4 py-2.5 font-medium">Targets</th>
                <th className="px-4 py-2.5 font-medium">Steps</th>
                <th className="px-4 py-2.5 font-medium">Recorded</th>
                <th className="px-4 py-2.5 font-medium">Tokens</th>
                <th className="px-4 py-2.5 font-medium">Error / summary</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={11} className="px-4 py-3 text-fg-muted">Loading...</td>
                </tr>
              )}
              {runs?.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-3 text-fg-muted">No runs yet.</td>
                </tr>
              )}
              {runs?.map((run) => (
                <tr key={run.id} className="border-b border-line last:border-b-0">
                  <td className="px-4 py-2.5">
                    <Link className="font-medium text-accent-strong hover:underline" to={`/ai/runs/${run.id}`}>
                      #{run.id}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{new Date(run.started_at).toLocaleString()}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{duration(run.started_at, run.finished_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <span className={run.status === 'error' ? 'font-medium text-red-600' : undefined}>
                      {run.status}
                    </span>
                    {run.dry_run ? ' (dry)' : ''}
                    {run.stop_reason === 'time_limit' && <span className="ml-1 text-xs text-amber-600">stopped at time limit</span>}
                    {run.stop_reason === 'manual' && <span className="ml-1 text-xs text-fg-muted">stopped by hand</span>}
                    {run.started_by === 'schedule' && <span className="ml-1 text-xs text-fg-subtle">scheduled</span>}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{run.entry_agent || '—'}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{run.model}</td>
                  <td className="max-w-56 truncate px-4 py-2.5 font-mono text-xs text-fg-muted" title={run.targets.join(', ')}>
                    {run.targets.join(', ')}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{run.step_count}</td>
                  <td className="px-4 py-2.5 tabular-nums">{run.services_recorded}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs tabular-nums text-fg-muted">
                    {run.prompt_tokens} / {run.completion_tokens}
                  </td>
                  <td className="max-w-72 truncate px-4 py-2.5 text-xs" title={run.error ?? run.summary ?? undefined}>
                    {run.error ? (
                      <span className="text-red-600">{run.error}</span>
                    ) : run.summary ? (
                      <span className="text-fg-muted">{run.summary}</span>
                    ) : (
                      <span className="text-fg-subtle">—</span>
                    )}
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
