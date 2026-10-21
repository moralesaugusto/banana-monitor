import { useMemo, useState } from 'react'
import type { AiRunDetail, BusMessage } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { explainMessage, messageText } from '../../lib/bus'
import { Json, explainStep } from './Trace'

type Kind = 'message' | 'llm' | 'tool' | 'error'

interface Entry {
  key: string
  ts: number
  agent: string
  kind: Kind
  what: string
  text: string
  explain: string
  detail: unknown
  meta: string
}

const KIND_STYLE: Record<Kind, { label: string; badge: string }> = {
  message: { label: 'Message', badge: 'bg-violet-500/20 text-violet-700 dark:text-violet-300' },
  llm: { label: 'Model', badge: 'bg-sky-500/20 text-sky-700 dark:text-sky-300' },
  tool: { label: 'Tool', badge: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300' },
  error: { label: 'Error', badge: 'bg-red-500/20 text-red-700 dark:text-red-300' },
}

const inputClasses = 'rounded-control border border-line bg-surface px-2 py-1 text-sm'

function stepText(response: unknown): string {
  const r = (response && typeof response === 'object' ? response : {}) as Record<string, unknown>
  if (typeof r.error === 'string') return r.error
  if (typeof r.content === 'string' && r.content) return r.content
  if (Array.isArray(r.tool_calls) && r.tool_calls.length > 0) {
    return `calls ${r.tool_calls.map((c: { name?: string }) => c.name).join(', ')}`
  }
  return JSON.stringify(response ?? '')
}

/** Bus messages and the agents' own model and tool steps, merged into one chronological list. */
function buildEntries(run: AiRunDetail, messages: BusMessage[]): Entry[] {
  const steps: Entry[] = run.steps.map((s) => ({
    key: `s${s.idx}`,
    ts: new Date(s.ts).getTime(),
    agent: s.agent ?? run.settings_snapshot.entry_agent?.toString() ?? '',
    kind: s.kind,
    what: s.name ?? '',
    text: stepText(s.response),
    explain: explainStep({ ...s, agent: null }),
    detail: { request: s.request, response: s.response },
    meta: `${s.duration_ms} ms${s.kind === 'llm' ? `, ${s.prompt_tokens} in / ${s.completion_tokens} out tokens` : ''}`,
  }))
  const bus: Entry[] = messages.map((m) => ({
    key: `m${m.id}`,
    ts: new Date(m.ts).getTime(),
    agent: m.sender,
    kind: 'message',
    what: m.topic,
    text: messageText(m),
    explain: explainMessage(m),
    detail: m.payload,
    meta: m.deliveries.length ? `to ${m.deliveries.map((d) => `${d.recipient} ${d.state}`).join(', ')}` : 'no subscribers',
  }))
  return [...steps, ...bus].sort((a, b) => a.ts - b.ts || a.key.localeCompare(b.key))
}

function Row({ entry }: { entry: Entry }) {
  const [open, setOpen] = useState(false)
  const style = KIND_STYLE[entry.kind]
  return (
    <>
      <tr className="cursor-pointer border-b border-line hover:bg-fg-subtle/5" onClick={() => setOpen(!open)}>
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-fg-muted">{new Date(entry.ts).toLocaleTimeString()}</td>
        <td className="whitespace-nowrap px-3 py-2 font-medium">{entry.agent}</td>
        <td className="whitespace-nowrap px-3 py-2">
          <span className={`rounded-full px-2 py-0.5 text-xs ${style.badge}`}>{style.label}</span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{entry.what}</td>
        <td className="max-w-96 truncate px-3 py-2 text-fg-muted" title={entry.text}>{entry.text}</td>
      </tr>
      {open && (
        <tr className="border-b border-line bg-fg-subtle/5">
          <td colSpan={5} className="px-3 py-3 text-sm">
            <p>{entry.explain}</p>
            <p className="mt-1 font-mono text-xs text-fg-muted">{entry.meta}</p>
            <div className="mt-2"><Json value={entry.detail} /></div>
          </td>
        </tr>
      )}
    </>
  )
}

export function RunLog({ run, messages }: { run: AiRunDetail; messages: BusMessage[] }) {
  const [agent, setAgent] = useState('')
  const [kind, setKind] = useState<'' | Kind>('')
  const [search, setSearch] = useState('')
  const entries = useMemo(() => buildEntries(run, messages), [run, messages])
  const agents = useMemo(() => [...new Set(entries.map((e) => e.agent).filter(Boolean))], [entries])
  const needle = search.toLowerCase()
  const visible = entries.filter(
    (e) =>
      (!agent || e.agent === agent) &&
      (!kind || e.kind === kind) &&
      (!needle || `${e.what} ${e.text}`.toLowerCase().includes(needle)),
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <input className={inputClasses} placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
        <select className={inputClasses} value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
          <option value="">All agents</option>
          {agents.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select className={inputClasses} value={kind} onChange={(e) => setKind(e.target.value as '' | Kind)} aria-label="Kind">
          <option value="">All kinds</option>
          {(Object.keys(KIND_STYLE) as Kind[]).map((k) => <option key={k} value={k}>{KIND_STYLE[k].label}</option>)}
        </select>
        <span className="text-fg-muted">{visible.length} of {entries.length} entries</span>
      </div>
      {visible.length === 0 ? (
        <p className="text-sm text-fg-muted">{run.status === 'running' ? 'Waiting for the agents...' : 'Nothing matches.'}</p>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-fg-muted">
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Agent</th>
                <th className="px-3 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Topic or tool</th>
                <th className="px-3 py-2 font-medium">Content</th>
              </tr>
            </thead>
            <tbody>{visible.map((e) => <Row key={e.key} entry={e} />)}</tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
