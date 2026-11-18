import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  agentLabel,
  type Agent,
  type AgentStateName,
  useAgentControl,
  useAgentMemory,
  useAgents,
  useAiModeSettings,
} from '../../api/aiMode'
import { useReports } from '../../api/reports'
import { Card } from '../../components/Card'
import { AgentRunButton, StateBadge } from './AgentStatus'
import {
  APPROVAL_LABELS,
  buttonClasses,
  charsToApproxTokens,
  effectiveProvider,
  groupTools,
  isInternetTool,
  keySummary,
  readersOf,
} from './agentFields'

function Chips({ items, empty, tone }: { items: string[]; empty: string; tone?: (item: string) => boolean }) {
  if (items.length === 0) return <span className="text-fg-subtle">{empty}</span>
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((i) => (
        <span
          key={i}
          className={`rounded-full px-2 py-0.5 font-mono text-xs ${
            tone?.(i) ? 'bg-red-500/15 text-red-700 dark:text-red-300' : 'bg-fg-subtle/15'
          }`}
        >
          {i}
        </span>
      ))}
    </span>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{title}</h2>
      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2 text-sm">{children}</dl>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

/** Notes this agent saved about itself with `remember` (docs/ai-agents.md), viewable and prunable here. */
function MemoryCard({ agent }: { agent: Agent }) {
  const { list, removeOne, clearAll } = useAgentMemory(agent.id)
  const entries = list.data ?? []

  return (
    <Card className="p-4" id="agent-memory">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          Memory {entries.length > 0 && `(${entries.length})`}
        </h2>
        {entries.length > 0 && (
          <button
            type="button"
            className="text-xs font-medium text-red-600 hover:underline"
            onClick={() => window.confirm(`Clear all ${entries.length} saved notes for ${agent.name}?`) && clearAll.mutate()}
          >
            Clear all
          </button>
        )}
      </div>
      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-fg-muted">
          No notes saved yet. {agent.enabled_tools.includes('remember') ? '' : 'Tick "remember" on the tools list to let this agent save notes for its future runs.'}
        </p>
      ) : (
        <ul className="mt-3 max-h-72 space-y-2 overflow-auto">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-start justify-between gap-3 rounded-control bg-canvas p-2 text-sm">
              <div className="min-w-0">
                <p className="break-words">{entry.content}</p>
                <p className="mt-1 text-xs text-fg-subtle">{new Date(entry.created_at).toLocaleString()}</p>
              </div>
              <button
                type="button"
                className="shrink-0 text-xs text-red-600 hover:underline"
                onClick={() => removeOne.mutate(entry.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** This agent's own saved reports (save_report tool), newest first - the Reports page shows every
    agent's reports together, so this is the quick "did it actually write one" view on the agent itself. */
function ReportsCard({ agent }: { agent: Agent }) {
  const { data: reports } = useReports()
  const mine = (reports ?? []).filter((r) => r.source === `agent:${agent.name}`)
  if (mine.length === 0) return null
  return (
    <Card className="p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
        Reports ({mine.length})
      </h2>
      <ul className="mt-3 space-y-2">
        {mine.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 text-sm">
            <Link to={`/reports?report=${r.id}`} className="min-w-0 truncate text-accent-strong hover:underline">
              {r.title}
            </Link>
            <span className="shrink-0 text-xs text-fg-subtle">{new Date(r.created_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** Every setting of one agent, read-only, in labelled sections. Editing happens on its own screen. */
export function AgentDetail({
  agent,
  all,
  state,
  queued,
  runActive,
  aiEnabled,
}: {
  agent: Agent
  all: Agent[]
  state: AgentStateName | undefined
  queued: number | undefined
  runActive: boolean
  aiEnabled: boolean
}) {
  const control = useAgentControl()
  const { remove } = useAgents()
  const navigate = useNavigate()
  const readers = readersOf(agent, all)
  const { data: defaults } = useAiModeSettings()
  const [targetInput, setTargetInput] = useState('')
  const [messageInput, setMessageInput] = useState('')
  const targets = targetInput.split(',').map((t) => t.trim()).filter(Boolean)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold" title={agent.name}>{agentLabel(agent)}</h2>
              <StateBadge state={state ?? (agent.enabled ? 'stopped' : 'disabled')} queued={queued} />
              {!!agent.memory_count && (
                <a
                  href="#agent-memory"
                  title={`${agent.memory_count} saved memory note(s) - jump to Memory`}
                  className="rounded-full bg-accent-soft-strong px-2 py-0.5 text-xs font-semibold text-accent-strong hover:underline"
                >
                  {agent.memory_count} memory note{agent.memory_count === 1 ? '' : 's'}
                </a>
              )}
            </div>
            <p className="mt-1 text-sm text-fg-muted">{agent.role || 'No role description.'}</p>
          </div>
          <div className="flex items-center gap-2">
            <Link to={`/ai/agents/${agent.name}/edit`} className={buttonClasses}>
              Edit
            </Link>
            <button
              type="button"
              className="rounded-control border border-red-500/50 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-500/10"
              onClick={() =>
                window.confirm(`Delete agent ${agent.name}?`) &&
                remove.mutate(agent.id, { onSuccess: () => navigate('/ai/agents') })
              }
            >
              Delete
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs text-fg-muted">
            Target (optional, comma-separated)
            <input
              type="text"
              placeholder="10.0.0.5, 10.0.0.6"
              className="mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg"
              value={targetInput}
              onChange={(e) => setTargetInput(e.target.value)}
            />
          </label>
          <label className="flex flex-col text-xs text-fg-muted">
            Task (optional)
            <input
              type="text"
              placeholder="What should this agent do?"
              className="mt-1 w-64 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg"
              value={messageInput}
              onChange={(e) => setMessageInput(e.target.value)}
            />
          </label>
        </div>
        <p className="mt-1 text-xs text-fg-subtle">
          A target does not need to already be a known device - the agent is free to look at it either way.
        </p>
        <AgentRunButton
          agent={agent}
          state={state}
          runActive={runActive}
          aiEnabled={aiEnabled}
          control={control}
          targets={targets}
          message={messageInput || null}
        />
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Model">
          <Row label="Provider">
            {(() => {
              const key = keySummary(agent, defaults)
              return (
                <span className={key.warn ? 'font-medium text-amber-700 dark:text-amber-300' : undefined}>
                  {key.text}
                  {!agent.provider && ' (agents\' default)'}
                </span>
              )
            })()}
          </Row>
          <Row label={effectiveProvider(agent, defaults) === 'openrouter' ? 'API base URL' : 'Ollama host'}>
            <span className="break-all font-mono text-xs">{agent.base_url || 'agents default'}</span>
          </Row>
          <Row label="Model">
            <span className="font-mono text-xs">{agent.model_override || 'agents default'}</span>
          </Row>
          <Row label="Temperature">{agent.temperature}</Row>
          <Row label="Loop limit">up to {agent.max_iterations} model calls per message</Row>
          <Row label="Remember">
            {agent.enabled_tools.includes('remember') ? (
              <>
                On - up to {agent.memory_max_entries_override || defaults?.memory_max_entries_per_agent || 30}{' '}
                notes, ~
                {charsToApproxTokens(
                  agent.memory_max_content_chars_override || defaults?.memory_max_content_chars || 200,
                )}{' '}
                tokens each, ~
                {charsToApproxTokens(
                  agent.memory_max_inject_chars_override || defaults?.memory_max_inject_chars || 4000,
                )}{' '}
                tokens injected per call
              </>
            ) : (
              <span className="text-fg-subtle">Off</span>
            )}
          </Row>
        </Section>

        <Section title="Safety">
          <Row label="Human in the loop">{APPROVAL_LABELS[agent.require_approval]}</Row>
          <Row label="Changes">
            {agent.allow_changes ? 'May change hosts; every change needs your approval' : 'Read-only'}
          </Row>
          <Row label="Stored credentials">
            {agent.credential_scope === 'pool'
              ? 'Host-bound integration first, then the credential pool'
              : agent.credential_scope === 'selected'
                ? `Host-bound integration first, then ${agent.credential_scope_ids?.length ?? 0} selected credential(s)`
                : 'Host-bound integrations only'}
          </Row>
          <Row label="Enabled">{agent.enabled ? 'Takes part in new runs' : 'Switched off'}</Row>
        </Section>
      </div>

      <Section title="Tools">
        {/* 'remember' has its own row under Model (above) - exclude it here so it isn't also
            listed as an uncategorized "custom" tool. */}
        {(() => {
          const shownTools = agent.enabled_tools.filter((t) => t !== 'remember')
          return shownTools.length === 0 ? (
            <Row label="Tools">
              <span className="text-fg-subtle">none</span>
            </Row>
          ) : (
            groupTools(shownTools).map((group) => (
              <Row key={group.id} label={group.label}>
                <Chips items={group.tools} empty="none" tone={group.id === 'internet' ? isInternetTool : undefined} />
              </Row>
            ))
          )
        })()}
        {agent.mcp_url_override && (
          <Row label="MCP server override">
            <span className="break-all font-mono text-xs">{agent.mcp_url_override}</span>
          </Row>
        )}
        {agent.mcp_timeout_seconds > 0 && (
          <Row label="MCP call timeout">{agent.mcp_timeout_seconds}s (default: 30s)</Row>
        )}
      </Section>

      <Section title="Messaging">
        <Row label="Listens to">
          <Chips items={agent.subscribes} empty="nothing" />
        </Row>
        <Row label="May publish to">
          <Chips items={agent.publishes} empty="nothing" />
        </Row>
        <Row label="Results go to">
          <Chips items={readers} empty={`nobody listens to result.${agent.name}`} />
        </Row>
      </Section>

      <ReportsCard agent={agent} />

      <MemoryCard agent={agent} />

      <Card className="p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">System prompt</h2>
        {agent.system_prompt ? (
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-control bg-canvas p-3 font-mono text-xs">
            {agent.system_prompt}
          </pre>
        ) : (
          <p className="mt-3 text-sm text-fg-muted">Empty: the default discovery prompt is used.</p>
        )}
      </Card>
    </div>
  )
}
