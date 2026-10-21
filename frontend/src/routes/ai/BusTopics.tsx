import { Fragment, useState } from 'react'
import { type BusTopicStats, useBusOverview, useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { messageText } from '../../lib/bus'

const STATES: { key: string; label: string; tone: string }[] = [
  { key: 'acked', label: 'handled', tone: 'text-emerald-700 dark:text-emerald-300' },
  { key: 'delivered', label: 'queued', tone: 'text-sky-700 dark:text-sky-300' },
  { key: 'pending', label: 'held', tone: 'text-amber-700 dark:text-amber-300' },
  { key: 'rejected', label: 'rejected', tone: 'text-red-700 dark:text-red-300' },
  { key: 'dropped', label: 'dropped', tone: 'text-fg-muted' },
]

function Outcomes({ topic }: { topic: BusTopicStats }) {
  const shown = STATES.filter((s) => topic.deliveries[s.key])
  if (shown.length === 0) return <span className="text-fg-subtle">no deliveries</span>
  return (
    <span className="flex flex-wrap gap-x-3">
      {shown.map((s) => (
        <span key={s.key} className={s.tone}>
          {topic.deliveries[s.key]} {s.label}
        </span>
      ))}
    </span>
  )
}

function TopicMessages({ topic, runId }: { topic: string; runId: number | null }) {
  const { data } = useMessages(runId ?? undefined, { topic, allRuns: runId === null })
  const exact = (data ?? []).filter((m) => m.topic === topic).slice(-10).reverse()
  return (
    <div className="flex flex-col gap-1 text-xs">
      {exact.length === 0 && <span className="text-fg-muted">Loading...</span>}
      {exact.map((m) => (
        <div key={m.id} className="rounded-control bg-fg-subtle/10 p-2">
          <span className="font-mono text-fg-muted">{new Date(m.ts).toLocaleTimeString()}</span>{' '}
          <span className="font-medium">{m.sender}</span>
          {m.deliveries.length > 0 && <span className="text-fg-muted"> to {m.deliveries.map((d) => `${d.recipient} (${d.state})`).join(', ')}</span>}
          <div className="mt-1 truncate" title={messageText(m)}>{messageText(m)}</div>
        </div>
      ))}
    </div>
  )
}

/** Traffic per topic for the selected run, or for every run. */
export function BusTopics({ runId }: { runId: number | null }) {
  const [allRuns, setAllRuns] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const scope = allRuns ? null : runId
  const { data } = useBusOverview(scope)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={allRuns} onChange={(e) => setAllRuns(e.target.checked)} />
          Include every run
        </label>
        {data && <span className="text-fg-muted">{data.total_messages} message(s) on {data.topics.length} topic(s)</span>}
      </div>

      {data && data.topics.length === 0 && <p className="text-sm text-fg-muted">No messages yet.</p>}
      {data && data.topics.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-fg-muted">
                <th className="px-3 py-2 font-medium">Topic</th>
                <th className="px-3 py-2 font-medium">Messages</th>
                <th className="px-3 py-2 font-medium">Published by</th>
                <th className="px-3 py-2 font-medium">Delivered to</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
                <th className="px-3 py-2 font-medium">Last</th>
              </tr>
            </thead>
            <tbody>
              {data.topics.map((t) => (
                <Fragment key={t.topic}>
                  <tr
                    className="cursor-pointer border-b border-line hover:bg-fg-subtle/5"
                    onClick={() => setOpen(open === t.topic ? null : t.topic)}
                  >
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{t.topic}</td>
                    <td className="px-3 py-2">
                      {t.messages}
                      {t.held > 0 && <span className="ml-2 rounded-full bg-amber-500/20 px-2 py-0.5 text-xs">{t.held} held</span>}
                    </td>
                    <td className="px-3 py-2">{t.publishers.join(', ')}</td>
                    <td className="px-3 py-2">{t.recipients.join(', ') || <span className="text-fg-subtle">no subscribers</span>}</td>
                    <td className="px-3 py-2 text-xs"><Outcomes topic={t} /></td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-fg-muted">{new Date(t.last_ts).toLocaleString()}</td>
                  </tr>
                  {open === t.topic && (
                    <tr className="border-b border-line bg-fg-subtle/5">
                      <td colSpan={6} className="px-3 py-3">
                        <TopicMessages topic={t.topic} runId={scope} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
