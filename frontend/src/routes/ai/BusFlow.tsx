import { useMemo, useState } from 'react'
import { type BusMessage, useAgents, useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { explainMessage, messageText } from '../../lib/bus'
import { FLOW_STROKE, type FlowTone, groupConversations, isRouted } from '../../lib/busFlow'
import { Json } from './Trace'

const EMPTY: BusMessage[] = []
const LEFT = 130
const COLUMN = 44
const LANE = 52
const TOP = 28

const STATE_LABEL: Record<string, string> = {
  acked: 'handled', delivered: 'queued', pending: 'held', rejected: 'rejected', dropped: 'dropped',
}

/** One lane per participant, one column per message in order: a dot where it was published, an arrow into each
 * lane that received it, coloured by what became of that delivery. */
export function BusFlow({ runId }: { runId: number | undefined }) {
  const { data: all = EMPTY } = useMessages(runId)
  const { data: agents } = useAgents().list
  const [conversation, setConversation] = useState('')
  const [upTo, setUpTo] = useState<number | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  const conversations = useMemo(() => groupConversations(all), [all])
  const scoped = useMemo(
    () => all.filter((m) => isRouted(m) && (!conversation || m.correlation_id === conversation)),
    [all, conversation],
  )
  const total = scoped.length
  const shown = upTo === null ? total : Math.min(upTo, total)
  const messages = scoped.slice(0, shown)

  const lanes = useMemo(() => {
    const names = new Set<string>(['human'])
    for (const a of (agents ?? []).filter((agent) => agent.enabled)) names.add(a.name)
    for (const m of scoped) {
      names.add(m.sender)
      for (const d of m.deliveries) names.add(d.recipient)
    }
    return [...names]
  }, [agents, scoped])
  const laneY = (name: string) => TOP + lanes.indexOf(name) * LANE
  const width = LEFT + Math.max(total, 1) * COLUMN + 30
  const height = TOP + lanes.length * LANE
  const detail = messages.find((m) => m.id === selected)

  if (runId === undefined) return <p className="text-sm text-fg-muted">No runs yet. Start one from AI Run.</p>

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select
          className="rounded-control border border-line bg-surface px-2 py-1 text-sm"
          value={conversation}
          aria-label="Conversation"
          onChange={(e) => { setConversation(e.target.value); setUpTo(null); setSelected(null) }}
        >
          <option value="">All conversations</option>
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>{c.id.slice(0, 8)}: {c.messages.length} message(s), {c.participants.join(', ')}</option>
          ))}
        </select>
        <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
          {(Object.keys(FLOW_STROKE) as FlowTone[]).map((tone) => (
            <span key={tone} className="flex items-center gap-1">
              <svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" strokeWidth="3" className={FLOW_STROKE[tone]} /></svg>
              {STATE_LABEL[tone]}
            </span>
          ))}
        </div>
      </div>

      <Card className="overflow-x-auto">
        <svg width={width} height={height} role="img" aria-label="Message flow between agents" className="min-w-full">
          <defs>
            <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-fg-muted" />
            </marker>
          </defs>
          {lanes.map((name) => (
            <g key={name}>
              <line x1={LEFT - 10} x2={width - 10} y1={laneY(name)} y2={laneY(name)} className="stroke-line" strokeDasharray="2 4" />
              <text x={LEFT - 18} y={laneY(name) + 4} textAnchor="end" className="fill-fg text-[12px] font-medium">{name}</text>
            </g>
          ))}
          {messages.map((m, i) => {
            const x = LEFT + i * COLUMN
            const y = laneY(m.sender)
            const isSelected = m.id === selected
            return (
              <g key={m.id} className="cursor-pointer" onClick={() => setSelected(m.id === selected ? null : m.id)}>
                <title>{`${m.sender} to ${m.topic}: ${messageText(m)}`}</title>
                {m.deliveries.map((d, j) => (
                  <line
                    key={d.recipient}
                    x1={x + j * 5} x2={x + j * 5} y1={y} y2={laneY(d.recipient)}
                    strokeWidth={2.5} markerEnd="url(#flow-arrow)"
                    className={FLOW_STROKE[d.state as FlowTone] ?? 'stroke-fg-subtle'}
                  />
                ))}
                <circle
                  cx={x} cy={y} r={isSelected ? 7 : 5}
                  className={`${m.status === 'held' ? 'fill-amber-500' : m.status === 'rejected' ? 'fill-red-500' : m.deliveries.length === 0 ? 'fill-fg-subtle' : 'fill-accent'} ${isSelected ? 'stroke-fg' : 'stroke-surface'}`}
                  strokeWidth={2}
                />
                <rect x={x - 12} y={TOP - 22} width={24} height={height} fill="transparent" />
              </g>
            )
          })}
          {total === 0 && <text x={LEFT} y={TOP + 4} className="fill-fg-muted text-sm">No messages yet.</text>}
        </svg>
        <div className="border-t border-line px-4 py-3 text-sm">
          <label className="flex flex-wrap items-center gap-3">
            <span className="text-fg-muted">Replay</span>
            <input
              type="range" min={0} max={total} value={shown} className="min-w-48 flex-1" aria-label="Replay position"
              onChange={(e) => setUpTo(Number(e.target.value) >= total ? null : Number(e.target.value))}
            />
            <span className="font-mono text-xs">{shown}/{total} messages</span>
            {upTo !== null && <button type="button" className="text-xs text-accent-strong hover:underline" onClick={() => setUpTo(null)}>Back to live</button>}
          </label>
        </div>
      </Card>

      {detail && <MessageDetail message={detail} />}
      {!detail && total > 0 && <p className="text-xs text-fg-muted">Click a dot to read the message. A grey dot had no subscribers, an amber one is held for a human.</p>}
    </div>
  )
}

function MessageDetail({ message }: { message: BusMessage }) {
  return (
    <Card className="p-4 text-sm">
      <p>{explainMessage(message)}</p>
      <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
        <dt className="text-fg-muted">Topic</dt><dd className="font-mono">{message.topic}</dd>
        <dt className="text-fg-muted">Hops</dt><dd>{message.hops}</dd>
        <dt className="text-fg-muted">Conversation</dt><dd className="font-mono">{message.correlation_id}</dd>
        <dt className="text-fg-muted">Deliveries</dt>
        <dd>{message.deliveries.map((d) => `${d.recipient}: ${STATE_LABEL[d.state] ?? d.state}`).join(', ') || 'none'}</dd>
      </dl>
      <div className="mt-2"><Json value={message.payload} /></div>
    </Card>
  )
}
