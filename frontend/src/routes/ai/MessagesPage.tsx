import { useMemo, useState } from 'react'
import { type BusMessage, useMessageActions, useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { explainMessage, messageText } from '../../lib/bus'
import { useSelectedRun } from '../../lib/useSelectedRun'
import { RunPicker } from './RunPicker'

const inputClasses = 'rounded-control border border-line bg-surface px-2 py-1 text-sm'
const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'

const STATE_STYLE: Record<string, string> = {
  pending: 'bg-amber-500/20 text-amber-700 dark:text-amber-300',
  delivered: 'bg-sky-500/20 text-sky-700 dark:text-sky-300',
  acked: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
  rejected: 'bg-red-500/20 text-red-700 dark:text-red-300',
  dropped: 'bg-fg-subtle/20 text-fg-muted',
}

function Recipients({ message }: { message: BusMessage }) {
  if (message.topic.startsWith('approval.')) return <span className="text-fg-subtle">human</span>
  if (message.deliveries.length === 0) return <span className="text-fg-subtle">no subscribers</span>
  return (
    <span className="flex flex-wrap gap-1">
      {message.deliveries.map((d) => (
        <span key={d.recipient} className={`rounded-full px-2 py-0.5 text-xs ${STATE_STYLE[d.state]}`} title={`delivery state: ${d.state}`}>
          {d.recipient} {d.state}
        </span>
      ))}
    </span>
  )
}

export function ApprovalCard({ message }: { message: BusMessage }) {
  const { approve, reject } = useMessageActions()
  const isTool = message.topic.startsWith('approval.tool.')
  const initial = isTool ? JSON.stringify((message.payload as { arguments?: unknown }).arguments ?? {}, null, 2) : messageText(message)
  const [text, setText] = useState(initial)
  const [error, setError] = useState<string | null>(null)

  function onApprove() {
    let payload: Record<string, unknown> | undefined
    if (text !== initial) {
      if (isTool) {
        try {
          payload = { tool: (message.payload as { tool?: string }).tool, arguments: JSON.parse(text) }
        } catch {
          setError('Arguments must be valid JSON')
          return
        }
      } else {
        payload = { text }
      }
    }
    approve.mutate({ id: message.id, payload }, { onError: (e) => setError(e.message) })
  }

  return (
    <Card className="border-amber-500/50 p-4">
      <div className="text-sm font-medium">
        {isTool
          ? `${message.sender} wants to run ${(message.payload as { tool?: string }).tool}`
          : `${message.sender} wants to publish to ${message.topic}`}
      </div>
      <p className="mt-1 text-xs text-fg-muted">{explainMessage(message)}</p>
      <textarea
        className={`${inputClasses} mt-2 h-24 w-full font-mono text-xs`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="Edit before approving"
      />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" className={buttonClasses} disabled={approve.isPending} onClick={onApprove}>
          {text !== initial ? 'Approve edited' : 'Approve'}
        </button>
        <button
          type="button"
          className={buttonClasses}
          disabled={reject.isPending}
          onClick={() => reject.mutate({ id: message.id, reason: window.prompt('Reason (the agent will see this)') ?? 'rejected' })}
        >
          Reject
        </button>
      </div>
    </Card>
  )
}

function SendAsHuman({ runId, correlationId }: { runId: number; correlationId?: string }) {
  const { send } = useMessageActions()
  const [topic, setTopic] = useState('task.discoverer')
  const [text, setText] = useState('')
  return (
    <Card className="p-4">
      <div className="text-sm font-medium">Send a message as the human</div>
      <p className="mt-1 text-xs text-fg-muted">
        You are a participant like any agent: publish to a topic and every agent subscribed to it receives it.
        Try <span className="font-mono">task.discoverer</span> or <span className="font-mono">human.reviewer</span>.
      </p>
      <form
        className="mt-2 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          send.mutate({ run_id: runId, topic, text, correlation_id: correlationId }, { onSuccess: () => setText('') })
        }}
      >
        <input className={`${inputClasses} w-56 font-mono`} value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Topic" />
        <input className={`${inputClasses} min-w-48 flex-1`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Message" aria-label="Message" />
        <button type="submit" className={buttonClasses} disabled={!text || send.isPending}>Publish</button>
      </form>
      {send.isError && <p className="mt-1 text-xs text-red-600">{send.error.message}</p>}
    </Card>
  )
}

function Row({ message }: { message: BusMessage }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr className="cursor-pointer border-b border-line hover:bg-fg-subtle/5" onClick={() => setOpen(!open)}>
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-fg-muted">{new Date(message.ts).toLocaleTimeString()}</td>
        <td className="whitespace-nowrap px-3 py-2 font-medium">{message.sender}</td>
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{message.topic}</td>
        <td className="px-3 py-2"><Recipients message={message} /></td>
        <td className="max-w-80 truncate px-3 py-2 text-fg-muted" title={messageText(message)}>
          {message.status === 'held' && <span className="mr-2 rounded-full bg-amber-500/20 px-2 py-0.5 text-xs">held</span>}
          {message.status === 'rejected' && <span className="mr-2 rounded-full bg-red-500/20 px-2 py-0.5 text-xs">rejected</span>}
          {messageText(message)}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-line bg-fg-subtle/5">
          <td colSpan={5} className="px-3 py-3 text-sm">
            <p>{explainMessage(message)}</p>
            <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
              <dt className="text-fg-muted">Message id</dt><dd className="font-mono">{message.id}</dd>
              <dt className="text-fg-muted">Conversation</dt><dd className="font-mono">{message.correlation_id}</dd>
              <dt className="text-fg-muted">Hops</dt><dd>{message.hops} (agent-to-agent steps from the original task; capped to stop loops)</dd>
              {message.reply_to && (<><dt className="text-fg-muted">Reply to</dt><dd className="font-mono">{message.reply_to}</dd></>)}
            </dl>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-control bg-fg-subtle/10 p-2 font-mono text-xs">{JSON.stringify(message.payload, null, 2)}</pre>
          </td>
        </tr>
      )}
    </>
  )
}

export function MessagesPage() {
  const { runs, run, setChosen } = useSelectedRun()
  const { data: messages = [] } = useMessages(run?.id)
  const [topicFilter, setTopicFilter] = useState('')
  const [senderFilter, setSenderFilter] = useState('')
  const [grouped, setGrouped] = useState(false)

  const held = messages.filter((m) => m.status === 'held')
  const senders = useMemo(() => [...new Set(messages.map((m) => m.sender))], [messages])
  const visible = messages.filter(
    (m) => m.topic.includes(topicFilter) && (!senderFilter || m.sender === senderFilter),
  )
  const conversations = useMemo(() => {
    const groups = new Map<string, BusMessage[]>()
    for (const m of visible) groups.set(m.correlation_id, [...(groups.get(m.correlation_id) ?? []), m])
    return [...groups.entries()]
  }, [visible])

  const header = (
    <thead>
      <tr className="border-b border-line text-left text-fg-muted">
        <th className="px-3 py-2 font-medium">Time</th>
        <th className="px-3 py-2 font-medium">Publisher</th>
        <th className="px-3 py-2 font-medium">Topic</th>
        <th className="px-3 py-2 font-medium">Delivered to</th>
        <th className="px-3 py-2 font-medium">Message</th>
      </tr>
    </thead>
  )

  return (
    <div>
      <PageHeader
        title="Messages"
        description="Every message agents publish to the bus, in order. A publisher never addresses a recipient: it names a topic, and the bus delivers to whoever subscribed. Click a row to see why it was delivered. Messages an agent must clear with you appear as approvals."
      />
      <div className="mt-4">
        <RunPicker runs={runs} run={run} onChange={setChosen} />
      </div>
      {!run && <p className="mt-6 text-sm text-fg-muted">No runs yet. Start one from AI Mode.</p>}

      {run && (
        <div className="mt-4 flex flex-col gap-4">
          {held.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-semibold">Waiting for you ({held.length})</h2>
              <div className="grid gap-3 lg:grid-cols-2">{held.map((m) => <ApprovalCard key={m.id} message={m} />)}</div>
            </div>
          )}
          {run.status === 'running' && <SendAsHuman runId={run.id} />}

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <input className={inputClasses} placeholder="Filter topic" value={topicFilter} onChange={(e) => setTopicFilter(e.target.value)} />
            <select className={inputClasses} value={senderFilter} onChange={(e) => setSenderFilter(e.target.value)} aria-label="Publisher">
              <option value="">All publishers</option>
              {senders.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />
              Group by conversation
            </label>
            <span className="text-fg-muted">{visible.length} message(s)</span>
          </div>

          {visible.length === 0 && <p className="text-sm text-fg-muted">No messages match.</p>}
          {!grouped && visible.length > 0 && (
            <Card className="overflow-x-auto">
              <table className="w-full text-sm">{header}<tbody>{visible.map((m) => <Row key={m.id} message={m} />)}</tbody></table>
            </Card>
          )}
          {grouped &&
            conversations.map(([id, items]) => (
              <Card key={id} className="overflow-x-auto">
                <div className="border-b border-line px-3 py-2 text-xs text-fg-muted">
                  Conversation <span className="font-mono">{id}</span>: {items.length} message(s) across{' '}
                  {new Set(items.map((m) => m.sender)).size} participant(s)
                </div>
                <table className="w-full text-sm">{header}<tbody>{items.map((m) => <Row key={m.id} message={m} />)}</tbody></table>
                {run.status === 'running' && <div className="border-t border-line p-3"><SendAsHuman runId={run.id} correlationId={id} /></div>}
              </Card>
            ))}
        </div>
      )}
    </div>
  )
}
