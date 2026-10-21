import { useBusHealth, type BusGauge } from '../../api/aiMode'
import { Card } from '../../components/Card'

function duration(seconds: number): string {
  const s = Math.round(seconds)
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`
}

function Gauge({ title, hint, gauge, format }: { title: string; hint: string; gauge: BusGauge; format?: (n: number) => string }) {
  const show = format ?? ((n: number) => String(n))
  const pct = gauge.limit ? Math.min(100, (gauge.used / gauge.limit) * 100) : 0
  const tone = pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-accent'
  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-sm font-medium">{title}</div>
        <div className="font-mono text-xs text-fg-muted">
          {show(gauge.used)}
          {gauge.limit !== null && ` / ${show(gauge.limit)}`}
        </div>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-fg-subtle/20"
        role="progressbar"
        aria-label={title}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-fg-muted">{hint}</p>
    </Card>
  )
}

/** Limits of the run, per-agent queues and anything stuck or discarded. */
export function BusHealth({ runId }: { runId: number | undefined }) {
  const { data: health } = useBusHealth(runId)
  if (runId === undefined) return <p className="text-sm text-fg-muted">No runs yet. Start one from AI Run.</p>
  if (!health) return null

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Gauge title="Messages" gauge={health.messages} hint="Messages agents may publish in one run before the bus refuses more." />
        <Gauge title="Deepest conversation (hops)" gauge={health.hops} hint="Agent-to-agent steps from the original task. At the limit the bus assumes a loop." />
        <Gauge title="Time" gauge={health.seconds} format={duration} hint="The run is stopped automatically when its time budget is used." />
      </div>

      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-fg-muted">
              <th className="px-3 py-2 font-medium">Agent</th>
              <th className="px-3 py-2 font-medium">Working</th>
              <th className="px-3 py-2 font-medium">Queued</th>
              <th className="px-3 py-2 font-medium">Waiting for you</th>
              <th className="px-3 py-2 font-medium">Dropped</th>
            </tr>
          </thead>
          <tbody>
            {health.agents.map((a) => (
              <tr key={a.name} className="border-b border-line">
                <td className="px-3 py-2 font-medium">{a.name}</td>
                <td className="px-3 py-2">{a.working ? 'yes' : <span className="text-fg-subtle">no</span>}</td>
                <td className="px-3 py-2">{health.active ? a.queued : <span className="text-fg-subtle">run ended</span>}</td>
                <td className={`px-3 py-2 ${a.held ? 'text-amber-700 dark:text-amber-300' : ''}`}>{a.held}</td>
                <td className={`px-3 py-2 ${a.dropped ? 'text-fg-muted' : 'text-fg-subtle'}`}>{a.dropped}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="p-4">
        <div className="text-sm font-medium">Waiting for a human ({health.held.length})</div>
        {health.held.length === 0 ? (
          <p className="mt-1 text-sm text-fg-muted">Nothing is waiting for approval.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {health.held.map((h) => (
              <li key={h.message_id}>
                <span className="font-medium">{h.sender}</span> <span className="font-mono text-xs">{h.topic}</span>{' '}
                <span className={h.overdue ? 'text-red-600' : 'text-fg-muted'}>
                  waiting {duration(h.age_seconds)}
                  {h.overdue && `, past the ${duration(health.approval_timeout_seconds)} limit: treated as rejected`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-4">
        <div className="text-sm font-medium">Problems ({health.problems.length})</div>
        {health.problems.length === 0 ? (
          <p className="mt-1 text-sm text-fg-muted">No rejected or dropped messages in this run.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {health.problems.map((p) => (
              <li key={`${p.kind}-${p.message_id}-${p.recipient}`}>
                <span className={`mr-2 rounded-full px-2 py-0.5 text-xs ${p.kind === 'rejected' ? 'bg-red-500/20' : 'bg-fg-subtle/20'}`}>{p.kind}</span>
                <span className="font-mono text-xs">{p.topic}</span> from {p.sender}: {p.reason}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
