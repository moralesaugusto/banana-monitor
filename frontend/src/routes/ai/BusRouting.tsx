import { useState } from 'react'
import { type Agent, type BusParty, useBusRoute } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { buildRouting } from '../../lib/busRouting'

const inputClasses = 'rounded-control border border-line bg-surface px-2 py-1 text-sm font-mono'

function Parties({ title, parties }: { title: string; parties: BusParty[] }) {
  return (
    <div>
      <div className="text-xs font-medium text-fg-muted">{title}</div>
      {parties.length === 0 ? (
        <div className="text-sm text-fg-subtle">nobody</div>
      ) : (
        <ul className="mt-1 flex flex-col gap-1 text-sm">
          {parties.map((p) => (
            <li key={p.agent}>
              <span className={p.enabled ? 'font-medium' : 'text-fg-muted line-through'}>{p.agent}</span>{' '}
              <span className="font-mono text-xs text-fg-muted">via {p.pattern}</span>
              {!p.enabled && <span className="ml-1 text-xs text-amber-600">switched off</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Ask the server who gets a message on a topic: the same matcher the bus routes with. */
function TopicTester() {
  const [topic, setTopic] = useState('')
  const route = useBusRoute(topic)
  return (
    <Card className="p-4">
      <div className="text-sm font-medium">Test a topic</div>
      <p className="mt-1 text-xs text-fg-muted">
        Type a concrete topic, such as <span className="font-mono">result.bellaco</span>, to see who would receive it and
        who is allowed to publish it.
      </p>
      <input
        className={`${inputClasses} mt-2 w-full max-w-sm`}
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        placeholder="result.bellaco"
        aria-label="Topic to test"
      />
      {route.data && !route.data.valid && (
        <p className="mt-2 text-sm text-amber-600">
          Not a concrete topic: use lowercase words separated by dots, without * or #.
        </p>
      )}
      {route.data?.valid && (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Parties title="Would be delivered to" parties={route.data.subscribers} />
          <Parties title="May be published by" parties={route.data.publishers} />
        </div>
      )}
    </Card>
  )
}

const CHIP = {
  publish: 'bg-accent/15 text-accent-strong',
  subscribe: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
}

export function BusRouting({ agents }: { agents: Agent[] }) {
  const { topics, problems } = buildRouting(agents)
  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-3xl text-sm text-fg-muted">
        Who may publish and who listens, per topic. <span className={`rounded px-1.5 ${CHIP.publish}`}>publishes</span> means the agent's
        publish list allows the topic; <span className={`rounded px-1.5 ${CHIP.subscribe}`}>listens</span> means one of its
        subscription patterns matches it. Hover a chip for the pattern that decided it.
      </p>

      {problems.length > 0 && (
        <Card className="p-4">
          <div className="text-sm font-medium">Things to check</div>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {problems.map((p) => (
              <li key={p.text} className={p.severity === 'warn' ? 'text-amber-700 dark:text-amber-400' : 'text-fg-muted'}>
                {p.severity === 'warn' ? 'Warning: ' : 'Note: '}
                {p.text}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <TopicTester />

      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-fg-muted">
              <th className="px-3 py-2 font-medium">Topic</th>
              {agents.map((a) => (
                <th key={a.id} className={`px-3 py-2 font-medium ${a.enabled ? '' : 'text-fg-subtle line-through'}`}>
                  {a.display_name || a.name}
                </th>
              ))}
              <th className="px-3 py-2 font-medium">Also published by</th>
            </tr>
          </thead>
          <tbody>
            {topics.map((t) => (
              <tr key={t.topic} className="border-b border-line">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{t.topic}</td>
                {agents.map((a) => {
                  const pub = t.publishers.find((p) => p.agent === a.name)
                  const sub = t.subscribers.find((s) => s.agent === a.name)
                  return (
                    <td key={a.id} className="whitespace-nowrap px-3 py-2">
                      <div className="flex gap-1">
                        {pub && <span className={`rounded px-1.5 py-0.5 text-xs ${CHIP.publish}`} title={`publish pattern ${pub.pattern}`}>publishes</span>}
                        {sub && <span className={`rounded px-1.5 py-0.5 text-xs ${CHIP.subscribe}`} title={`subscription ${sub.pattern}`}>listens</span>}
                      </div>
                    </td>
                  )
                })}
                <td className="px-3 py-2 text-xs text-fg-muted">{t.implicit ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
