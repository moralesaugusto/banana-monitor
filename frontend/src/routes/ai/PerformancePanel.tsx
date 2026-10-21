import { usePerformance, useResetPerformance } from '../../api/aiPerformance'
import { Card } from '../../components/Card'

const n = (value: number) => value.toLocaleString()
const ms = (value: number) => (value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`)
const cell = 'px-3 py-2 text-right font-mono tabular-nums'
const head = 'px-3 py-2 text-right text-xs font-medium text-fg-muted'

function Table({ children }: { children: React.ReactNode }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </Card>
  )
}

export function PerformancePanel() {
  const { data, isPending, error } = usePerformance()
  const reset = useResetPerformance()
  if (isPending) return <p className="mt-6 text-sm text-fg-muted">Loading...</p>
  if (error) return <p className="mt-6 text-sm text-red-600">{error.message}</p>

  const agentRows = data.by_agent
  const modelRows = data.by_model
  const agentModelRows = data.by_agent_model
  const slowest = agentRows.length
    ? agentRows.reduce((a, b) => (b.avg_duration_ms > a.avg_duration_ms ? b : a))
    : null

  return (
    <div className="mt-6 flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">
          How long each agent's model calls actually take, and how each model compares - so a slow
          host, model or agent shows up here rather than just as a run that feels sluggish.{' '}
          {data.since
            ? `Counting since the reset on ${new Date(data.since).toLocaleString()}.`
            : 'Based on stored run history (the same traces the Run History page shows).'}{' '}
          Clearing run history, or an AI Mode reset, clears this too, unlike the token counters on the
          Cost tab.
        </p>
        <button
          type="button"
          disabled={reset.isPending}
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50"
          onClick={() => {
            if (window.confirm('Reset performance stats? Run history and Cost keep their own numbers.')) {
              reset.mutate()
            }
          }}
        >
          Reset stats
        </button>
      </div>

      {slowest && agentRows.length > 1 && (
        <p className="text-xs text-fg-muted">
          Slowest on average: <span className="font-medium text-fg">{slowest.agent}</span> at{' '}
          {ms(slowest.avg_duration_ms)} per call ({slowest.models.join(', ') || 'no model recorded'}).
        </p>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">By agent</h2>
        <Table>
          <thead>
            <tr className="border-b border-line">
              <th className={`${head} text-left`}>Agent</th>
              <th className={`${head} text-left`}>Model(s)</th>
              <th className={head}>Calls</th>
              <th className={head}>Errors</th>
              <th className={head}>Avg latency</th>
              <th className={head}>Min</th>
              <th className={head}>Max</th>
              <th className={head}>Tokens/sec out</th>
            </tr>
          </thead>
          <tbody>
            {agentRows.map((a) => (
              <tr key={a.agent} className="border-b border-line last:border-0">
                <td className="px-3 py-2">{a.agent}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.models.join(', ') || '-'}</td>
                <td className={cell}>{n(a.calls)}</td>
                <td className={cell}>
                  {a.errors > 0 ? <span className="text-red-600 dark:text-red-400">{n(a.errors)}</span> : 0}
                </td>
                <td className={cell}>{ms(a.avg_duration_ms)}</td>
                <td className={cell}>{ms(a.min_duration_ms)}</td>
                <td className={cell}>{ms(a.max_duration_ms)}</td>
                <td className={cell}>{a.tokens_per_second ? a.tokens_per_second.toFixed(1) : '-'}</td>
              </tr>
            ))}
            {agentRows.length === 0 && (
              <tr>
                <td className="px-3 py-3 text-sm text-fg-muted" colSpan={8}>
                  No model calls recorded yet. Start a run to see latency per agent.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-sm font-semibold">By agent and model</h2>
          <p className="text-xs text-fg-muted">
            For each agent, its own breakdown per model it has actually run with - useful when an
            agent switched models over time: the "By agent" average above blends them together, this
            keeps them apart.
          </p>
        </div>
        {agentRows.map((a) => {
          const rows = agentModelRows.filter((r) => r.agent === a.agent)
          if (rows.length === 0) return null
          return (
            <div key={a.agent}>
              <h3 className="mb-1 text-xs font-medium text-fg-muted">{a.agent}</h3>
              <Table>
                <thead>
                  <tr className="border-b border-line">
                    <th className={`${head} text-left`}>Model</th>
                    <th className={head}>Calls</th>
                    <th className={head}>Avg latency</th>
                    <th className={head}>Min</th>
                    <th className={head}>Max</th>
                    <th className={head}>Tokens/sec out</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.model} className="border-b border-line last:border-0">
                      <td className="px-3 py-2 font-mono text-xs">{r.model}</td>
                      <td className={cell}>{n(r.calls)}</td>
                      <td className={cell}>{ms(r.avg_duration_ms)}</td>
                      <td className={cell}>{ms(r.min_duration_ms)}</td>
                      <td className={cell}>{ms(r.max_duration_ms)}</td>
                      <td className={cell}>{r.tokens_per_second ? r.tokens_per_second.toFixed(1) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )
        })}
        {agentModelRows.length === 0 && (
          <p className="text-sm text-fg-muted">No model calls recorded yet.</p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">By model</h2>
        <p className="text-xs text-fg-muted">
          Compare models head to head across whichever agents have used them - useful before switching
          an agent to a model it hasn't tried yet, or back to one it has.
        </p>
        <Table>
          <thead>
            <tr className="border-b border-line">
              <th className={`${head} text-left`}>Model</th>
              <th className={`${head} text-left`}>Used by</th>
              <th className={head}>Calls</th>
              <th className={head}>Avg latency</th>
              <th className={head}>Min</th>
              <th className={head}>Max</th>
              <th className={head}>Tokens/sec out</th>
            </tr>
          </thead>
          <tbody>
            {modelRows.map((m) => (
              <tr key={m.model} className="border-b border-line last:border-0">
                <td className="px-3 py-2 font-mono text-xs">{m.model}</td>
                <td className="px-3 py-2">{m.agents.join(', ') || '-'}</td>
                <td className={cell}>{n(m.calls)}</td>
                <td className={cell}>{ms(m.avg_duration_ms)}</td>
                <td className={cell}>{ms(m.min_duration_ms)}</td>
                <td className={cell}>{ms(m.max_duration_ms)}</td>
                <td className={cell}>{m.tokens_per_second ? m.tokens_per_second.toFixed(1) : '-'}</td>
              </tr>
            ))}
            {modelRows.length === 0 && (
              <tr>
                <td className="px-3 py-3 text-sm text-fg-muted" colSpan={7}>
                  No model calls recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      </section>
    </div>
  )
}
