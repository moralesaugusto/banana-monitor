import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  agentLabel,
  type Agent,
  type AgentInput,
  type ApprovalMode,
  type VerifyResult,
  useAgents,
  useAiModeSettings,
  useAiModeTools,
  useAiStatus,
  useCustomTools,
  useListOllamaModels,
  useVerifyAgent,
} from '../../api/aiMode'
import { errorDetail } from '../../api/auth'
import { usePerformance } from '../../api/aiPerformance'
import { useCreateCredential } from '../../api/credentials'
import { Card } from '../../components/Card'
import {
  APPROVAL_LABELS,
  EMPTY,
  agentNameError,
  buttonClasses,
  firstSentence,
  groupTools,
  inputClasses,
  isInternetTool,
  primaryClasses,
  splitList,
  toInput,
} from './agentFields'
import { VerifyPanel } from './VerifyPanel'

const CHANGING_TOOLS = ['apply_updates']

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-sm">{children}</div>
    </Card>
  )
}

function AgentEditForm({ initial }: { initial: Agent | null }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { save } = useAgents()
  const verify = useVerifyAgent()
  const { data: tools } = useAiModeTools()
  const custom = useCustomTools()
  const { data: defaults } = useAiModeSettings()
  const { data: aiStatus } = useAiStatus()
  const { data: performance } = usePerformance()
  const listModels = useListOllamaModels()
  const createCredential = useCreateCredential()
  const [apiKey, setApiKey] = useState('')

  const [baseline, setBaseline] = useState<AgentInput>(initial ? toInput(initial) : EMPTY)
  const [draft, setDraft] = useState<AgentInput>(baseline)
  const [subscribes, setSubscribes] = useState(baseline.subscribes.join(', '))
  const [publishes, setPublishes] = useState(baseline.publishes.join(', '))
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [result, setResult] = useState<VerifyResult | null>(
    (location.state as { verify?: VerifyResult } | null)?.verify ?? null,
  )

  const set = <K extends keyof AgentInput>(key: K, value: AgentInput[K]) => {
    setSaved(false)
    setDraft({ ...draft, [key]: value })
  }
  const current = (): AgentInput => ({ ...draft, subscribes: splitList(subscribes), publishes: splitList(publishes) })
  const dirty = JSON.stringify(current()) !== JSON.stringify(baseline)
  const back = initial ? `/ai/agents/${initial.name}` : '/ai/agents'

  const descriptions: Record<string, string> = {
    ...Object.fromEntries((tools?.tools ?? []).map((t) => [t.name, t.description])),
    ...Object.fromEntries((custom.list.data ?? []).map((t) => [t.name, t.description])),
  }
  const toolNames = Object.keys(descriptions)

  function nameInvalid(): boolean {
    const message = initial === null ? agentNameError(draft.name) : null
    setError(message)
    return message !== null
  }

  function runVerify() {
    if (nameInvalid()) return
    verify.mutate({ input: current(), agentId: initial?.id }, { onSuccess: setResult })
  }

  async function persist(thenVerify: boolean) {
    if (nameInvalid()) return
    setSaved(false)
    let input = current()
    if (apiKey && (input.provider || defaults?.llm_provider) === 'openrouter') {
      try {
        const credential = await createCredential.mutateAsync({
          label: `OpenRouter API key (${input.name})`,
          credential_type: 'api_token',
          secret: { token: apiKey },
        })
        input = { ...input, credential_id: credential.id }
        setDraft((d) => ({ ...d, credential_id: credential.id }))
        setApiKey('')
      } catch (err) {
        setError(errorDetail(err instanceof Error ? err : null))
        return
      }
    }
    save.mutate(
      { id: initial?.id, input },
      {
        onError: (err) => setError(errorDetail(err)),
        onSuccess: (agent) => {
          const input = toInput(agent)
          setBaseline(input)
          setSaved(true)
          if (!thenVerify) {
            navigate(`/ai/agents/${agent.name}`)
            return
          }
          verify.mutate(
            { input, agentId: agent.id },
            {
              onSuccess: (verified) => {
                setResult(verified)
                // A new agent now exists: the URL becomes its edit URL so the next save is an update.
                if (initial === null) navigate(`/ai/agents/${agent.name}/edit`, { replace: true, state: { verify: verified } })
              },
            },
          )
        },
      },
    )
  }

  function cancel() {
    if (dirty && !window.confirm('Discard your changes?')) return
    navigate(back)
  }

  const busy = save.isPending || verify.isPending
  const status = save.isPending
    ? 'Saving…'
    : verify.isPending
      ? 'Verifying…'
      : error
        ? error
        : saved
          ? 'Saved.'
          : dirty
            ? 'Unsaved changes'
            : ''

  return (
    <div>
      <Link to={back} className="text-sm text-fg-muted hover:underline">
        {initial ? `← ${agentLabel(initial)}` : '← Agents'}
      </Link>
      <div className="sticky top-0 z-10 -mx-4 mt-2 border-b border-line bg-surface/95 px-4 py-3 backdrop-blur md:-mx-6 md:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-medium tracking-tight">{initial ? `Edit ${agentLabel(initial)}` : 'New agent'}</h1>
          <span role="status" className={`text-xs ${error ? 'text-red-600 dark:text-red-400' : 'text-fg-muted'}`}>
            {status}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button type="button" className={buttonClasses} onClick={cancel}>
              Cancel
            </button>
            <button type="button" className={buttonClasses} disabled={busy} onClick={runVerify}>
              Verify
            </button>
            <button type="submit" form="agent-form" className={buttonClasses} disabled={busy}>
              {initial ? 'Save' : 'Add agent'}
            </button>
            <button type="button" className={primaryClasses} disabled={busy} onClick={() => persist(true)}>
              Save and verify
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <form
          id="agent-form"
          className="flex min-w-0 flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            persist(false)
          }}
        >
          <Panel title="Identity">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                Name
                <input
                  className={inputClasses}
                  value={draft.name}
                  placeholder="reviewer"
                  disabled={initial !== null}
                  onChange={(e) => set('name', e.target.value)}
                />
                <span className="mt-1 block text-xs text-fg-muted">
                  The stable identifier other settings refer to (schedule, manual run); cannot change once created.
                </span>
              </label>
              <label>
                Display name (shown in the UI instead of Name; optional)
                <input
                  className={inputClasses}
                  value={draft.display_name ?? ''}
                  placeholder={draft.name || 'e.g. Master Discoverer'}
                  onChange={(e) => set('display_name', e.target.value || null)}
                />
              </label>
            </div>
            <label>
              Role (one line the other agents see)
              <input className={inputClasses} value={draft.role} onChange={(e) => set('role', e.target.value)} />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={draft.enabled} onChange={(e) => set('enabled', e.target.checked)} />
              Enabled (takes part in new runs)
            </label>
            <p className="text-xs text-fg-muted">
              This is independent of the global "Enable AI Mode" switch under Settings: that switch is a kill-switch
              for starting any run at all; this checkbox decides only whether this one agent takes part when a run
              starts. You can enable AI Mode and leave this agent disabled while other agents run, or the reverse.
            </p>
          </Panel>

          <Panel title="Model">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                Provider
                <select
                  className={inputClasses}
                  value={draft.provider}
                  onChange={(e) => set('provider', e.target.value as AgentInput['provider'])}
                >
                  <option value="">Use the agents' default{defaults ? ` (${defaults.llm_provider})` : ''}</option>
                  <option value="ollama">Ollama</option>
                  <option value="openrouter">OpenRouter</option>
                </select>
              </label>
              {(draft.provider || defaults?.llm_provider) === 'openrouter' && (
                <label>
                  API key{' '}
                  {draft.credential_id
                    ? '(leave blank to keep this agent\'s key)'
                    : '(blank uses the default key)'}
                  <input
                    type="password"
                    className={inputClasses}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-or-..."
                  />
                </label>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                {(draft.provider || defaults?.llm_provider) === 'openrouter' ? 'API base URL' : 'Ollama host'} (empty uses
                the {draft.provider && draft.provider !== defaults?.llm_provider ? "provider's standard address" : `agents' default${defaults ? `: ${defaults.llm_base_url}` : ''}`})
                <input
                  className={`${inputClasses} font-mono`}
                  value={draft.base_url}
                  placeholder="http://localhost:11434/v1"
                  onChange={(e) => set('base_url', e.target.value)}
                />
              </label>
              <label>
                Model (empty uses the agents' default{defaults ? `: ${defaults.llm_model}` : ''})
                <div className="flex gap-2">
                  <input
                    className={`${inputClasses} font-mono`}
                    list="ollama-models"
                    value={draft.model_override}
                    onChange={(e) => set('model_override', e.target.value)}
                  />
                  <button
                    type="button"
                    className={`${buttonClasses} mt-1 shrink-0`}
                    disabled={listModels.isPending}
                    onClick={() => listModels.mutate(draft.base_url)}
                  >
                    {listModels.isPending ? 'Loading…' : 'Load models'}
                  </button>
                </div>
                <datalist id="ollama-models">
                  {listModels.data?.models.map((m) => <option key={m} value={m} />)}
                </datalist>
                {listModels.isError && (
                  <span className="text-xs text-red-600 dark:text-red-400">{listModels.error.message}</span>
                )}
                {listModels.data && (
                  <span className="text-xs text-fg-muted">
                    {listModels.data.models.length} model(s) on {listModels.data.base_url}
                  </span>
                )}
                {performance && draft.model_override && (() => {
                  const stats = performance.by_model.find((m) => m.model === draft.model_override)
                  return stats ? (
                    <p className="mt-1 text-xs text-fg-muted">
                      Used before (by {stats.agents.join(', ')}): avg {stats.avg_duration_ms >= 1000
                        ? `${(stats.avg_duration_ms / 1000).toFixed(1)}s`
                        : `${Math.round(stats.avg_duration_ms)}ms`} per call, {stats.tokens_per_second.toFixed(1)} tok/s over {stats.calls} call(s). See the Performance tab for details.
                    </p>
                  ) : (
                    <p className="mt-1 text-xs text-fg-muted">No performance history yet for this model.</p>
                  )
                })()}
              </label>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                Temperature
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  className={inputClasses}
                  value={draft.temperature}
                  onChange={(e) => set('temperature', Number(e.target.value))}
                />
              </label>
              <label>
                Loop limit (model calls per message)
                <input
                  type="number"
                  min={1}
                  max={60}
                  className={inputClasses}
                  value={draft.max_iterations}
                  onChange={(e) => set('max_iterations', Number(e.target.value))}
                />
              </label>
              <label>
                Model call timeout (seconds, 0 uses the default{defaults ? `: ${defaults.llm_call_timeout_seconds}` : ''})
                <input
                  type="number"
                  min={0}
                  max={1800}
                  className={inputClasses}
                  value={draft.llm_timeout_seconds ?? 0}
                  onChange={(e) => set('llm_timeout_seconds', Number(e.target.value))}
                />
              </label>
              <label>
                Run time limit (minutes, 0 uses the default{aiStatus ? `: ${aiStatus.schedule.max_run_minutes}` : ''})
                <input
                  type="number"
                  min={0}
                  max={240}
                  className={inputClasses}
                  value={draft.max_run_minutes ?? 0}
                  onChange={(e) => set('max_run_minutes', Number(e.target.value))}
                />
              </label>
            </div>
          </Panel>

          <Panel title="Tools">
            {groupTools(toolNames).map((group) => (
              <fieldset key={group.id}>
                <legend className="text-xs font-medium text-fg-muted">{group.label}</legend>
                <div className="mt-1 flex flex-col gap-1.5">
                  {group.tools.map((tool) => (
                    <label key={tool} className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={draft.enabled_tools.includes(tool)}
                        onChange={(e) =>
                          set(
                            'enabled_tools',
                            e.target.checked ? [...draft.enabled_tools, tool] : draft.enabled_tools.filter((t) => t !== tool),
                          )
                        }
                      />
                      <span className="min-w-0">
                        <span className="font-mono">{tool}</span>
                        {isInternetTool(tool) && <span className="ml-2 text-xs font-medium text-red-600 dark:text-red-400">internet</span>}
                        {CHANGING_TOOLS.includes(tool) && (
                          <span className="ml-2 text-xs font-medium text-amber-700 dark:text-amber-300">changes hosts</span>
                        )}
                        <span className="block text-xs text-fg-muted">{firstSentence(descriptions[tool] ?? '')}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            {!draft.allow_changes && draft.enabled_tools.some((t) => CHANGING_TOOLS.includes(t)) && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                A tool that changes hosts is ticked: also tick "May change hosts" under Safety.
              </p>
            )}
            <label>
              MCP server override (empty uses each custom tool's own address)
              <input
                className={`${inputClasses} font-mono`}
                value={draft.mcp_url_override ?? ''}
                placeholder="http://192.168.1.10:8891/mcp"
                onChange={(e) => set('mcp_url_override', e.target.value || null)}
              />
              <span className="mt-1 block text-xs text-fg-muted">
                Replaces the mcp_url of every custom tool this agent calls, for this agent only. Point this
                agent at a new host (e.g. a replacement HexStrike VM) without editing each custom tool.
              </span>
            </label>
            <label>
              MCP call timeout, seconds (0 uses the default: 30)
              <input
                type="number"
                min={0}
                max={600}
                className={inputClasses}
                value={draft.mcp_timeout_seconds}
                onChange={(e) => set('mcp_timeout_seconds', Number(e.target.value))}
              />
              <span className="mt-1 block text-xs text-fg-muted">
                How long this agent waits for one MCP custom tool call before giving up. A built-in tool
                enforces its own short timeout, but an MCP tool can be anything a remote server chooses to
                run (a full port scan, a brute-force attempt). 30 seconds is too short for some of those -
                the call is cut off mid-run, which looks like a dead server ("MCP call failed: ReadTimeout")
                and wastes an iteration rather than reporting a real result. Raise this if a run's trace
                shows that error on a tool call that should genuinely take longer.
              </span>
            </label>
          </Panel>

          <Panel title="Messaging">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                Subscribes to (topic patterns, comma separated)
                <input
                  className={`${inputClasses} font-mono`}
                  value={subscribes}
                  placeholder="task.reviewer, discovery.#"
                  onChange={(e) => {
                    setSaved(false)
                    setSubscribes(e.target.value)
                  }}
                />
              </label>
              <label>
                May publish to
                <input
                  className={`${inputClasses} font-mono`}
                  value={publishes}
                  placeholder="result.#"
                  onChange={(e) => {
                    setSaved(false)
                    setPublishes(e.target.value)
                  }}
                />
              </label>
            </div>
          </Panel>

          <Panel title="Safety">
            <label>
              Human in the loop
              <select
                className={inputClasses}
                value={draft.require_approval}
                onChange={(e) => set('require_approval', e.target.value as ApprovalMode)}
              >
                {(Object.keys(APPROVAL_LABELS) as ApprovalMode[]).map((m) => (
                  <option key={m} value={m}>
                    {APPROVAL_LABELS[m]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={draft.allow_changes} onChange={(e) => set('allow_changes', e.target.checked)} />
              May change hosts (needed for apply_updates; every change still waits for your approval)
            </label>
          </Panel>

          <Panel title="System prompt">
            <label>
              System prompt (empty uses the default discovery prompt)
              <textarea
                className={`${inputClasses} h-64 font-mono text-xs`}
                value={draft.system_prompt}
                placeholder={tools?.default_system_prompt}
                onChange={(e) => set('system_prompt', e.target.value)}
              />
            </label>
          </Panel>
        </form>

        <aside className="xl:sticky xl:top-24">
          <VerifyPanel result={result} pending={verify.isPending} error={errorDetail(verify.error)} />
        </aside>
      </div>
    </div>
  )
}

/** The edit screen for `/ai/agents/new` (no :name) and `/ai/agents/:name/edit`. */
export function AgentEditPage() {
  const { name } = useParams<{ name: string }>()
  const agents = useAgents()
  if (name === undefined) return <AgentEditForm key="new" initial={null} />
  if (agents.list.isPending) return <p className="text-sm text-fg-muted">Loading…</p>
  const agent = agents.list.data?.find((a) => a.name === name)
  if (!agent) {
    return (
      <p className="text-sm">
        There is no agent called <span className="font-mono">{name}</span>.{' '}
        <Link to="/ai/agents" className="font-medium text-accent-strong hover:underline">
          Back to the agents
        </Link>
      </p>
    )
  }
  return <AgentEditForm key={agent.id} initial={agent} />
}
