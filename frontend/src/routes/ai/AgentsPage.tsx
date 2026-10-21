import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { agentLabel, type Agent, type AgentStateName, useAgents, useAiStatus } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { Segmented } from '../../components/Segmented'
import { AgentDetail } from './AgentDetail'
import { RunStatusPanel, SchedulePanel, StateBadge } from './AgentStatus'
import { buttonClasses, inputClasses } from './agentFields'

type StateFilter = 'all' | 'running' | 'stopped' | 'disabled'

const RUNNING: AgentStateName[] = ['working', 'waiting', 'paused']

function matchesFilter(filter: StateFilter, state: AgentStateName): boolean {
  if (filter === 'all') return true
  if (filter === 'running') return RUNNING.includes(state)
  return filter === 'disabled' ? state === 'disabled' : state === 'stopped' || state === 'scheduled'
}

function AgentRow({ agent, state, queued, selected }: { agent: Agent; state: AgentStateName; queued: number; selected: boolean }) {
  return (
    <Link
      to={`/ai/agents/${agent.name}`}
      aria-current={selected ? 'page' : undefined}
      className={`block rounded-control border px-3 py-2 transition-colors ${
        selected ? 'border-accent bg-accent-soft-strong' : 'border-transparent hover:bg-fg-subtle/10'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold" title={agent.name}>{agentLabel(agent)}</span>
        <StateBadge state={state} queued={queued} />
      </div>
      <div className="mt-0.5 truncate text-xs text-fg-muted">{agent.role || 'No role description.'}</div>
      <div className="mt-0.5 text-xs text-fg-subtle">
        {agent.enabled_tools.length} tool(s){agent.allow_changes ? ', may change hosts' : ''}
      </div>
    </Link>
  )
}

export function AgentsPage() {
  const { name } = useParams<{ name: string }>()
  const agents = useAgents()
  const { data: status } = useAiStatus()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StateFilter>('all')

  const all = agents.list.data ?? []
  const info = (agent: Agent) => status?.agents.find((a) => a.name === agent.name)
  const stateOf = (agent: Agent): AgentStateName => info(agent)?.state ?? (agent.enabled ? 'stopped' : 'disabled')
  const selected = name ? all.find((a) => a.name === name) : all[0]

  const needle = query.trim().toLowerCase()
  const visible = all.filter(
    (a) =>
      matchesFilter(filter, stateOf(a)) &&
      (needle === '' ||
        [a.name, a.display_name ?? '', a.role, ...a.enabled_tools].some((text) => text.toLowerCase().includes(needle))),
  )

  return (
    <div>
      <PageHeader
        title="Agents"
        description="Each agent has its own instructions, model, tools and loop limit. Agents never call each other: they subscribe to topics and publish to topics, and the message bus delivers. Pick an agent to see all of its settings; Edit opens it on its own screen."
        actions={
          <Link to="/ai/agents/new" className={buttonClasses}>
            Add agent
          </Link>
        }
      />
      <RunStatusPanel />
      <div className="mt-6 grid items-start gap-4 lg:grid-cols-[21rem_minmax(0,1fr)]">
        <Card className="p-3 lg:sticky lg:top-4">
          <input
            type="search"
            aria-label="Search agents"
            placeholder="Search name, role or tool"
            className={inputClasses}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="mt-2">
            <Segmented<StateFilter>
              label="State filter"
              value={filter}
              onChange={setFilter}
              options={[
                { value: 'all', label: 'All' },
                { value: 'running', label: 'Running' },
                { value: 'stopped', label: 'Stopped' },
                { value: 'disabled', label: 'Disabled' },
              ]}
            />
          </div>
          <nav aria-label="Agents" className="mt-3 flex flex-col gap-1">
            {visible.map((agent) => (
              <AgentRow
                key={agent.id}
                agent={agent}
                state={stateOf(agent)}
                queued={info(agent)?.queued ?? 0}
                selected={agent.id === selected?.id}
              />
            ))}
            {visible.length === 0 && (
              <p className="px-1 py-2 text-sm text-fg-muted">
                {agents.list.isPending ? 'Loading…' : all.length === 0 ? 'No agents yet.' : 'No agent matches.'}
              </p>
            )}
          </nav>
        </Card>
        {selected ? (
          <AgentDetail
            key={selected.id}
            agent={selected}
            all={all}
            state={info(selected)?.state}
            queued={info(selected)?.queued}
            runActive={status?.run != null}
            aiEnabled={status?.ai_enabled ?? false}
          />
        ) : (
          !agents.list.isPending && (
            <Card className="p-4 text-sm">
              {name ? (
                <>
                  There is no agent called <span className="font-mono">{name}</span>.{' '}
                  <Link to="/ai/agents" className="font-medium text-accent-strong hover:underline">
                    Back to the agents
                  </Link>
                </>
              ) : (
                'Add an agent to get started.'
              )}
            </Card>
          )
        )}
      </div>
      <SchedulePanel />
    </div>
  )
}
