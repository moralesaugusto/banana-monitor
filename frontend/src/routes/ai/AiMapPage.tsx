import { useMemo, useState } from 'react'
import { type Agent, type BusMessage, useAgents, useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { explainMessage, messageText, NODE_HUMAN, topicMatches } from '../../lib/bus'
import { ApprovalCard } from './MessagesPage'
import { useSelectedRun } from '../../lib/useSelectedRun'
import { RunPicker } from './RunPicker'

const W = 860
const H = 560
const CX = W / 2
const CY = H / 2

interface MapNode {
  id: string
  kind: 'agent' | 'topic'
  label: string
  x: number
  y: number
}

function layout(agentNames: string[], topics: string[]): Map<string, MapNode> {
  const nodes = new Map<string, MapNode>()
  agentNames.forEach((name, i) => {
    const angle = (2 * Math.PI * i) / Math.max(agentNames.length, 1) - Math.PI / 2
    nodes.set(`a:${name}`, { id: `a:${name}`, kind: 'agent', label: name, x: CX + 330 * Math.cos(angle), y: CY + 215 * Math.sin(angle) })
  })
  topics.forEach((topic, i) => {
    const angle = (2 * Math.PI * i) / Math.max(topics.length, 1) - Math.PI / 2
    const r = topics.length === 1 ? 0 : 120
    nodes.set(`t:${topic}`, { id: `t:${topic}`, kind: 'topic', label: topic, x: CX + r * 1.25 * Math.cos(angle), y: CY + r * Math.sin(angle) })
  })
  return nodes
}

/** Half-extent to clear a node's own shape, so a line (and its arrowhead) ends at the node's edge
 * instead of its center - otherwise the node (drawn on top, so it can be clicked) paints over the
 * line's last few pixels and hides the arrowhead that shows direction. */
function nodeRadius(node: MapNode): number {
  return node.kind === 'agent' ? 55 : Math.max(50, node.label.length * 3.6 + 6)
}

function Edge({
  a, b, steps, dashed, active, tone,
}: { a: MapNode; b: MapNode; steps: number[]; dashed?: boolean; active?: boolean; tone: string }) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const dist = Math.hypot(dx, dy) || 1
  const ux = dx / dist
  const uy = dy / dist
  const x1 = a.x + ux * nodeRadius(a)
  const y1 = a.y + uy * nodeRadius(a)
  const x2 = b.x - ux * nodeRadius(b)
  const y2 = b.y - uy * nodeRadius(b)
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const label = steps.length > 4 ? `#${steps.slice(0, 4).join(',')}…` : `#${steps.join(',')}`
  return (
    <g>
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        className={`${tone} ${active ? 'animate-pulse' : ''}`}
        strokeWidth={dashed ? 1 : Math.min(1.5 + steps.length, 6)}
        strokeDasharray={dashed ? '4 4' : active ? '8 4' : undefined}
        markerEnd="url(#arrow)"
        opacity={dashed ? 0.45 : 0.9}
      />
      {steps.length > 0 && !dashed && (
        <text x={mx} y={my - 4} textAnchor="middle" className="fill-fg text-[11px] font-semibold">
          {label}
        </text>
      )}
    </g>
  )
}

function agentOf(agents: Agent[] | undefined, name: string) {
  return agents?.find((a) => a.name === name)
}

export function AiMapPage() {
  const { runs, run, setChosen } = useSelectedRun()
  const { data: all = [] } = useMessages(run?.id)
  const { list } = useAgents()
  const agents = list.data
  const [upTo, setUpTo] = useState<number | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const total = all.length
  const shown = upTo === null ? total : Math.min(upTo, total)
  const messages = useMemo(() => all.slice(0, shown), [all, shown])
  const latest = messages.at(-1)

  const model = useMemo(() => {
    const routed = messages.filter((m) => !m.topic.startsWith('approval.'))
    const topics = [...new Set(routed.map((m) => m.topic))]
    const names = [...new Set([...(agents ?? []).filter((a) => a.enabled).map((a) => a.name), ...routed.map((m) => m.sender)])]
    if (!names.includes(NODE_HUMAN)) names.push(NODE_HUMAN)
    // Step numbers are each message's 1-indexed position in run order (excluding approval.* traffic,
    // which never appears on this diagram), so they stay stable as the replay slider moves forward.
    const published = new Map<string, number[]>()
    const delivered = new Map<string, number[]>()
    routed.forEach((m, i) => {
      const step = i + 1
      const pubKey = `${m.sender}|${m.topic}`
      published.set(pubKey, [...(published.get(pubKey) ?? []), step])
      for (const d of m.deliveries) {
        const delKey = `${m.topic}|${d.recipient}`
        delivered.set(delKey, [...(delivered.get(delKey) ?? []), step])
      }
    })
    return { routed, topics, names, published, delivered, nodes: layout(names, topics) }
  }, [messages, agents])

  const heldTopics = new Set(messages.filter((m) => m.status === 'held' && !m.topic.startsWith('approval.')).map((m) => m.topic))
  const heldAgents = new Set(messages.filter((m) => m.status === 'held').map((m) => m.sender))
  const held = all.filter((m) => m.status === 'held')

  const selectedAgent = selected?.startsWith('a:') ? agentOf(agents, selected.slice(2)) : undefined
  const selectedTopic = selected?.startsWith('t:') ? selected.slice(2) : undefined
  const topicMessages: BusMessage[] = selectedTopic ? model.routed.filter((m) => m.topic === selectedTopic).slice(-6) : []

  return (
    <div>
      <PageHeader
        title="Map"
        description="Agents sit on the outer ring; topics sit in the middle. A solid arrow from an agent to a topic is a publish, a solid arrow from a topic to an agent is a delivery - the arrowhead shows which way the message moved. The numbers on each arrow (#1, #4, #9, ...) are those messages' step order within this run, not a count, so you can trace the sequence across the diagram. Faint dashed arrows with no number are subscriptions that have not carried traffic yet: that is how a wildcard pattern decides who receives what."
      />
      <div className="mt-4">
        <RunPicker runs={runs} run={run} onChange={setChosen} />
      </div>

      {run && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_300px]">
          <Card className="overflow-hidden">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Agent communication map">
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" className="fill-fg-muted" />
                </marker>
              </defs>
              {/* declared subscriptions: pattern -> topics it matches */}
              {model.topics.flatMap((topic) =>
                (agents ?? [])
                  .filter((a) => a.enabled && a.subscribes.some((p) => topicMatches(p, topic)))
                  .filter((a) => !model.delivered.has(`${topic}|${a.name}`))
                  .map((a) => {
                    const t = model.nodes.get(`t:${topic}`)
                    const n = model.nodes.get(`a:${a.name}`)
                    return t && n ? <Edge key={`s-${topic}-${a.name}`} a={t} b={n} steps={[]} dashed tone="stroke-fg-subtle" /> : null
                  }),
              )}
              {[...model.published].map(([key, steps]) => {
                const [sender, topic] = key.split('|')
                const a = model.nodes.get(`a:${sender}`)
                const t = model.nodes.get(`t:${topic}`)
                const active = latest?.sender === sender && latest.topic === topic
                return a && t ? <Edge key={`p-${key}`} a={a} b={t} steps={steps} active={active} tone="stroke-accent" /> : null
              })}
              {[...model.delivered].map(([key, steps]) => {
                const [topic, recipient] = key.split('|')
                const t = model.nodes.get(`t:${topic}`)
                const a = model.nodes.get(`a:${recipient}`)
                const active = latest?.topic === topic && latest.deliveries.some((d) => d.recipient === recipient)
                return a && t ? <Edge key={`d-${key}`} a={t} b={a} steps={steps} active={active} tone="stroke-emerald-500" /> : null
              })}
              {[...model.nodes.values()].map((node) => {
                const isAgent = node.kind === 'agent'
                const name = node.label
                const pulsing = isAgent ? heldAgents.has(name) : heldTopics.has(name)
                return (
                  <g key={node.id} transform={`translate(${node.x},${node.y})`} className="cursor-pointer" onClick={() => setSelected(node.id)}>
                    {isAgent ? (
                      <rect x={-48} y={-18} width={96} height={36} rx={10}
                        className={`${name === NODE_HUMAN ? 'fill-accent-soft' : 'fill-surface-raised'} ${selected === node.id ? 'stroke-accent' : 'stroke-line-strong'} ${pulsing ? 'animate-pulse stroke-amber-500' : ''}`}
                        strokeWidth={selected === node.id || pulsing ? 2.5 : 1.5} />
                    ) : (
                      <ellipse rx={Math.max(48, node.label.length * 3.6)} ry={15}
                        className={`fill-surface ${selected === node.id ? 'stroke-accent' : 'stroke-fg-subtle'} ${pulsing ? 'animate-pulse stroke-amber-500' : ''}`}
                        strokeWidth={selected === node.id || pulsing ? 2.5 : 1} />
                    )}
                    <text textAnchor="middle" dy="4" className={`fill-fg ${isAgent ? 'text-[12px] font-semibold' : 'font-mono text-[10px]'}`}>
                      {node.label}
                    </text>
                  </g>
                )
              })}
              {model.routed.length === 0 && (
                <text x={CX} y={CY} textAnchor="middle" className="fill-fg-muted text-sm">No messages yet in this run.</text>
              )}
            </svg>
            <div className="border-t border-line px-4 py-3 text-sm">
              <label className="flex flex-wrap items-center gap-3">
                <span className="text-fg-muted">Replay</span>
                <input
                  type="range" min={0} max={total} value={shown} className="min-w-48 flex-1"
                  aria-label="Replay position"
                  onChange={(e) => setUpTo(Number(e.target.value) >= total ? null : Number(e.target.value))}
                />
                <span className="font-mono text-xs">{shown}/{total} messages</span>
                {upTo !== null && (
                  <button type="button" className="text-xs text-accent-strong hover:underline" onClick={() => setUpTo(null)}>
                    Back to live
                  </button>
                )}
              </label>
              {latest && <p className="mt-2 text-xs text-fg-muted">Latest: {explainMessage(latest)}</p>}
            </div>
          </Card>

          <div className="flex flex-col gap-4">
            <Card className="p-4 text-sm">
              {!selected && <p className="text-fg-muted">Click an agent or a topic to inspect it.</p>}
              {selectedAgent && (
                <div className="flex flex-col gap-2">
                  <div className="font-mono font-semibold">{selectedAgent.name}</div>
                  <p className="text-fg-muted">{selectedAgent.role}</p>
                  <div><span className="text-fg-muted">Listens to:</span> <span className="font-mono text-xs">{selectedAgent.subscribes.join(', ') || 'nothing'}</span></div>
                  <div><span className="text-fg-muted">May publish:</span> <span className="font-mono text-xs">{selectedAgent.publishes.join(', ') || 'nothing'}</span></div>
                  <div><span className="text-fg-muted">Tools:</span> <span className="font-mono text-xs">{selectedAgent.enabled_tools.join(', ') || 'none'}</span></div>
                  <div><span className="text-fg-muted">Human gate:</span> {selectedAgent.require_approval}</div>
                </div>
              )}
              {selected === `a:${NODE_HUMAN}` && <p>You. Anything you publish from the Messages page appears here as a message from <span className="font-mono">human</span>.</p>}
              {selectedTopic && (
                <div className="flex flex-col gap-2">
                  <div className="font-mono font-semibold">{selectedTopic}</div>
                  <p className="text-fg-muted">
                    Subscribers: {(agents ?? []).filter((a) => a.subscribes.some((p) => topicMatches(p, selectedTopic))).map((a) => a.name).join(', ') || 'none'}
                  </p>
                  {topicMessages.map((m) => (
                    <div key={m.id} className="rounded-control bg-fg-subtle/10 p-2 text-xs">
                      <span className="font-medium">{m.sender}</span>: {messageText(m)}
                    </div>
                  ))}
                </div>
              )}
            </Card>
            {held.map((m) => <ApprovalCard key={m.id} message={m} />)}
          </div>
        </div>
      )}
      {!run && <p className="mt-6 text-sm text-fg-muted">No runs yet. Start one from AI Mode.</p>}
    </div>
  )
}
