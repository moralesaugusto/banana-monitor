import { useMemo } from 'react'
import { useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { messageText } from '../../lib/bus'
import { groupConversations } from '../../lib/busFlow'

function span(start: string, end: string): string {
  const seconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000)
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`
}

/** Each conversation (one task and everything it caused), indented by hop depth. */
export function BusConversations({ runId }: { runId: number | undefined }) {
  const { data: messages = [] } = useMessages(runId)
  const conversations = useMemo(() => groupConversations(messages), [messages])
  if (runId === undefined) return <p className="text-sm text-fg-muted">No runs yet. Start one from AI Run.</p>
  if (conversations.length === 0) return <p className="text-sm text-fg-muted">No conversations in this run yet.</p>

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-3xl text-sm text-fg-muted">
        A conversation starts with a task and includes every message it causes. The indent is the hop count: how many agent-to-agent
        steps the message is from the original task.
      </p>
      {conversations.map((c) => (
        <Card key={c.id} className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="text-sm font-medium">
              <span className="font-mono text-xs">{c.id.slice(0, 8)}</span>{' '}
              <span className="text-fg-muted">{c.messages.length} message(s), {c.participants.join(', ')}</span>
            </div>
            <div className="text-xs text-fg-muted">
              deepest hop {c.maxHops}, {span(c.start, c.end)}
              {c.held > 0 && <span className="ml-2 rounded-full bg-amber-500/20 px-2 py-0.5">{c.held} held</span>}
            </div>
          </div>
          <ol className="mt-3 flex flex-col gap-1.5 text-sm">
            {c.messages.map((m) => (
              <li key={m.id} style={{ paddingLeft: `${m.hops * 20}px` }} className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-xs text-fg-muted">{new Date(m.ts).toLocaleTimeString()}</span>
                <span className="font-medium">{m.sender}</span>
                <span className="text-fg-muted">to</span>
                <span className="font-mono text-xs">{m.topic}</span>
                <span className="text-fg-muted">
                  {m.deliveries.length ? `(${m.deliveries.map((d) => d.recipient).join(', ')})` : '(nobody)'}
                </span>
                {m.status !== 'delivered' && <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs">{m.status}</span>}
                <span className="max-w-xl truncate text-fg-muted" title={messageText(m)}>{messageText(m)}</span>
              </li>
            ))}
          </ol>
        </Card>
      ))}
    </div>
  )
}
