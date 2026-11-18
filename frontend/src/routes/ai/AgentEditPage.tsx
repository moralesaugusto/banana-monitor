import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  agentLabel,
  type Agent,
  type AgentInput,
  type ApprovalMode,
  type CredentialScope,
  type VerifyResult,
  useAgents,
  useAiModeSettings,
  useAiModeTools,
  useAiStatus,
  useCustomTools,
  useListOllamaModels,
  useTestAgentConnection,
  useVerifyAgent,
} from '../../api/aiMode'
import { errorDetail } from '../../api/auth'
import { usePerformance } from '../../api/aiPerformance'
import { useCreateCredential, useCredentials } from '../../api/credentials'
import { Card } from '../../components/Card'
import {
  APPROVAL_LABELS,
  applyConnectionMode,
  connectionMode,
  EMPTY,
  agentNameError,
  approxTokensToChars,
  buttonClasses,
  charsToApproxTokens,
  type ConnectionMode,
  firstSentence,
  groupTools,
  inputClasses,
  isInternetTool,
  keySummary,
  primaryClasses,
  splitList,
  toInput,
} from './agentFields'
import { OpenRouterKeyPicker } from './OpenRouterKeyPicker'
import { VerifyPanel } from './VerifyPanel'

const CHANGING_TOOLS = ['apply_updates']

const CONNECTION_MODE_OPTIONS: { value: ConnectionMode; label: string }[] = [
  { value: 'ollama_default', label: 'Use existing Ollama setting' },
  { value: 'openrouter_default', label: 'Use existing OpenRouter credentials' },
  { value: 'custom', label: 'Custom' },
]

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-sm">{children}</div>
    </Card>
  )
}

const SCOPE_OPTIONS: { value: CredentialScope; label: string; help: string }[] = [
  {
    value: 'bound',
    label: 'Host-bound integrations only',
    help: 'Only an integration set up for that host. The original behavior.',
  },
  {
    value: 'pool',
    label: 'Also try the credential pool',
    help: "After a host's own integration, try the credentials marked 'In agent pool' on the Credentials tab.",
  },
  {
    value: 'selected',
    label: 'Also try only the credentials I select',
    help: 'Same, but limited to the credentials ticked below, pooled or not.',
  },
]

/** Which stored credentials the host-inspection tools may try for this agent. A host's own integration
 * always comes first, whatever is chosen here. */
function CredentialScopePanel({
  scope,
  ids,
  onScope,
  onIds,
}: {
  scope: CredentialScope
  ids: number[]
  onScope: (value: CredentialScope) => void
  onIds: (value: number[]) => void
}) {
  const { data: credentials } = useCredentials()
  const toggle = (id: number) => onIds(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id])
  return (
    <Panel title="Stored credentials">
      <p className="text-xs text-fg-muted">
        For host-inspection tools (ssh_readonly, winrm_readonly, proxmox_get, apply_updates). The agent gives a host and
        Banana picks a credential: the integration bound to that host first, then, if allowed here, other stored
        credentials of the right kind. Safeguards for this are under AI Mode &gt; Settings &gt; Discovery.
      </p>
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Credential scope</legend>
        {SCOPE_OPTIONS.map((option) => (
          <label key={option.value} className="flex items-start gap-2">
            <input
              type="radio"
              name="credential-scope"
              className="mt-1"
              checked={scope === option.value}
              onChange={() => onScope(option.value)}
            />
            <span>
              {option.label}
              <span className="block text-xs text-fg-subtle">{option.help}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {scope === 'selected' && (
        <div className="rounded-control border border-line p-3">
          {credentials && credentials.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {credentials.map((credential) => (
                <li key={credential.id}>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={ids.includes(credential.id)} onChange={() => toggle(credential.id)} />
                    {credential.label}
                    <span className="text-xs text-fg-subtle">{credential.credential_type}</span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-fg-muted">No stored credentials yet. Add some on the Integrations page, Credentials tab.</p>
          )}
        </div>
      )}
    </Panel>
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
  const testConnection = useTestAgentConnection()
  const createCredential = useCreateCredential()
  const [apiKey, setApiKey] = useState('')
  const [fallbackApiKey, setFallbackApiKey] = useState('')

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
  // Which radio is selected - its own state, not derived from the current field values on every
  // render: once Custom is picked, it must stay picked even if every field in it is then cleared
  // back to blank (which would otherwise be indistinguishable from "ollama_default"/"openrouter_
  // default" by value alone). Guessed once from the saved agent when the agents' default loads,
  // unless the user has already clicked a radio themselves.
  const [mode, setMode] = useState<ConnectionMode>(() => connectionMode(baseline, defaults))
  const modeTouched = useRef(false)
  useEffect(() => {
    if (!modeTouched.current && defaults) setMode(connectionMode(baseline, defaults))
  }, [defaults, baseline])

  function selectMode(next: ConnectionMode) {
    modeTouched.current = true
    setApiKey('')
    setSaved(false)
    setMode(next)
    setDraft((d) => applyConnectionMode(next, d, defaults))
  }

  const current = (): AgentInput => ({ ...draft, subscribes: splitList(subscribes), publishes: splitList(publishes) })
  const dirty = JSON.stringify(current()) !== JSON.stringify(baseline)
  const back = initial ? `/ai/agents/${initial.name}` : '/ai/agents'

  const descriptions: Record<string, string> = {
    ...Object.fromEntries((tools?.tools ?? []).map((t) => [t.name, t.description])),
    ...Object.fromEntries((custom.list.data ?? []).map((t) => [t.name, t.description])),
  }
  // 'remember' has its own checkbox in the Model panel (a configuration choice, not a situational
  // tool), so it's excluded here rather than falling into the Tools panel's "Custom tools" bucket.
  const toolNames = Object.keys(descriptions).filter((name) => name !== 'remember')

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
    if ((input.provider || defaults?.llm_provider) === 'openrouter' && !input.credential_id && !defaults?.llm_credential_id) {
      setError("Enter an OpenRouter API key for this agent, or set a default under AI Mode > Settings > General.")
      return
    }
    if (fallbackApiKey && input.fallback_provider === 'openrouter') {
      try {
        const credential = await createCredential.mutateAsync({
          label: `OpenRouter API key (${input.name} fallback)`,
          credential_type: 'api_token',
          secret: { token: fallbackApiKey },
        })
        input = { ...input, fallback_credential_id: credential.id }
        setDraft((d) => ({ ...d, fallback_credential_id: credential.id }))
        setFallbackApiKey('')
      } catch (err) {
        setError(errorDetail(err instanceof Error ? err : null))
        return
      }
    }
    if (input.fallback_provider === 'openrouter' && !input.fallback_credential_id) {
      setError('Enter an OpenRouter API key for the fallback model, or clear the fallback provider.')
      return
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
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-xs font-medium text-fg">Connection</legend>
              {CONNECTION_MODE_OPTIONS.map(({ value, label }) => (
                <label key={value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="connection-mode"
                    checked={mode === value}
                    onChange={() => selectMode(value)}
                  />
                  {label}
                </label>
              ))}
              {mode !== 'custom' && (
                <p className="text-xs text-fg-muted">
                  Pins this agent to {mode === 'ollama_default' ? 'Ollama' : 'OpenRouter'} using today's existing
                  setting. Unlike leaving this blank in an older install, it will not silently follow a later
                  change to the agents' default provider under Settings &gt; General.
                </p>
              )}
            </fieldset>
            {(() => {
              const key = keySummary(draft, defaults)
              return (
                <span className={`block text-xs ${key.warn ? 'font-medium text-amber-700 dark:text-amber-300' : 'text-fg-muted'}`}>
                  Will use: {key.text}
                  {key.warn && (
                    <>
                      {' - '}
                      <Link to="/ai/config" className="underline">
                        pick or paste one under Settings
                      </Link>
                      .
                    </>
                  )}
                </span>
              )
            })()}
            {mode === 'custom' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <label>
                  Provider
                  <select
                    className={inputClasses}
                    value={draft.provider}
                    onChange={(e) => set('provider', e.target.value as AgentInput['provider'])}
                  >
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
                    <OpenRouterKeyPicker
                      inputClasses={inputClasses}
                      credentialId={draft.credential_id}
                      onSelectCredential={(id) => set('credential_id', id)}
                      apiKey={apiKey}
                      onChangeApiKey={setApiKey}
                    />
                  </label>
                )}
              </div>
            )}
            {mode === 'custom' && (
              <label>
                {(draft.provider || defaults?.llm_provider) === 'openrouter' ? 'API base URL' : 'Ollama host'} (empty uses
                the provider's standard address)
                <input
                  className={`${inputClasses} font-mono`}
                  value={draft.base_url}
                  placeholder={
                    (draft.provider || defaults?.llm_provider) === 'openrouter'
                      ? 'https://openrouter.ai/api/v1'
                      : 'http://localhost:11434/v1'
                  }
                  onChange={(e) => set('base_url', e.target.value)}
                />
              </label>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              {mode !== 'ollama_default' && (
                <label>
                  Model{' '}
                  {mode === 'custom' ? `(empty uses the agents' default${defaults ? `: ${defaults.llm_model}` : ''})` : ''}
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
                      onClick={() => listModels.mutate({ baseUrl: draft.base_url, provider: draft.provider })}
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
                  {performance && baseline.model_override && (() => {
                    // Keyed off the saved model (baseline), not the live keystroke-by-keystroke
                    // draft: looking up a half-typed model name flickered between "found" and "no
                    // history" on every character, and shifted everything below it on the page.
                    const stats = performance.by_model.find((m) => m.model === baseline.model_override)
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
              )}
              <div className={mode === 'ollama_default' ? '' : 'self-start'}>
                <span className="block text-xs text-fg-muted">&nbsp;</span>
                <button
                  type="button"
                  className={buttonClasses}
                  disabled={testConnection.isPending}
                  onClick={() =>
                    testConnection.mutate({
                      provider: draft.provider,
                      base_url: draft.base_url,
                      model: draft.model_override,
                      credential_id: draft.credential_id,
                      api_key: apiKey || undefined,
                    })
                  }
                >
                  {testConnection.isPending ? 'Testing…' : 'Test connection'}
                </button>
              </div>
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
            <div className="border-t border-line pt-3">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={(draft.fallback_provider ?? '') !== ''}
                  onChange={(e) => {
                    setFallbackApiKey('')
                    setDraft((d) => ({
                      ...d,
                      fallback_provider: e.target.checked ? 'ollama' : '',
                      fallback_base_url: '',
                      fallback_model: '',
                      fallback_credential_id: null,
                    }))
                  }}
                />
                Fallback model (retried once if the primary call fails)
              </label>
              {(draft.fallback_provider ?? '') !== '' && (
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  <label>
                    Fallback provider
                    <select
                      className={inputClasses}
                      value={draft.fallback_provider}
                      onChange={(e) => set('fallback_provider', e.target.value as AgentInput['fallback_provider'])}
                    >
                      <option value="ollama">Ollama</option>
                      <option value="openrouter">OpenRouter</option>
                    </select>
                  </label>
                  <label>
                    Fallback model
                    <input
                      className={`${inputClasses} font-mono`}
                      value={draft.fallback_model}
                      onChange={(e) => set('fallback_model', e.target.value)}
                    />
                  </label>
                  <label className="sm:col-span-2">
                    Fallback host (empty uses the provider's standard address)
                    <input
                      className={`${inputClasses} font-mono`}
                      value={draft.fallback_base_url}
                      placeholder={
                        draft.fallback_provider === 'openrouter'
                          ? 'https://openrouter.ai/api/v1'
                          : 'http://localhost:11434/v1'
                      }
                      onChange={(e) => set('fallback_base_url', e.target.value)}
                    />
                  </label>
                  {draft.fallback_provider === 'openrouter' && (
                    <label className="sm:col-span-2">
                      Fallback API key{' '}
                      {draft.fallback_credential_id
                        ? "(leave blank to keep this agent's fallback key)"
                        : '(blank uses the default key)'}
                      <OpenRouterKeyPicker
                        inputClasses={inputClasses}
                        credentialId={draft.fallback_credential_id ?? null}
                        onSelectCredential={(id) => set('fallback_credential_id', id)}
                        apiKey={fallbackApiKey}
                        onChangeApiKey={setFallbackApiKey}
                        ariaLabel="Stored OpenRouter key (fallback)"
                      />
                    </label>
                  )}
                </div>
              )}
            </div>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={draft.enabled_tools.includes('remember')}
                onChange={(e) =>
                  set(
                    'enabled_tools',
                    e.target.checked
                      ? [...draft.enabled_tools, 'remember']
                      : draft.enabled_tools.filter((t) => t !== 'remember'),
                  )
                }
              />
              <span>
                Remember
                <span className="block text-xs text-fg-muted">
                  Lets this agent save short notes for its own future runs (the `remember` tool) and get
                  its most recent ones back in its system prompt next time. Configuration, not a
                  situational tool, so it lives here rather than in Tools. See the Memory section on this
                  agent's page to view or clear what it has saved.
                </span>
              </span>
            </label>
            {draft.enabled_tools.includes('remember') && (
              <div className="grid gap-3 sm:grid-cols-3 rounded-control bg-canvas p-3">
                <label>
                  Max notes kept (0 uses the default: {defaults?.memory_max_entries_per_agent ?? 50})
                  <input
                    type="number"
                    min={0}
                    max={500}
                    className={inputClasses}
                    value={draft.memory_max_entries_override}
                    onChange={(e) => set('memory_max_entries_override', Number(e.target.value))}
                  />
                </label>
                <label>
                  Max size per note, ~tokens (0 uses the default: ~
                  {charsToApproxTokens(defaults?.memory_max_content_chars ?? 200)})
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    className={inputClasses}
                    value={draft.memory_max_content_chars_override ? charsToApproxTokens(draft.memory_max_content_chars_override) : 0}
                    onChange={(e) =>
                      set('memory_max_content_chars_override', approxTokensToChars(Number(e.target.value)))
                    }
                  />
                </label>
                <label>
                  Max injected per call, ~tokens (0 uses the default: ~
                  {charsToApproxTokens(defaults?.memory_max_inject_chars ?? 4000)})
                  <input
                    type="number"
                    min={0}
                    max={5000}
                    className={inputClasses}
                    value={draft.memory_max_inject_chars_override ? charsToApproxTokens(draft.memory_max_inject_chars_override) : 0}
                    onChange={(e) =>
                      set('memory_max_inject_chars_override', approxTokensToChars(Number(e.target.value)))
                    }
                  />
                </label>
              </div>
            )}
          </Panel>

          <Panel title="Tools">
            {groupTools(toolNames).map((group) => (
              <details key={group.id} className="group">
                <summary className="cursor-pointer select-none text-xs font-medium text-fg-muted">
                  {group.label}{' '}
                  <span className="text-fg-subtle">
                    ({group.tools.filter((t) => draft.enabled_tools.includes(t)).length}/{group.tools.length} on)
                  </span>
                </summary>
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
              </details>
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
                placeholder="http://10.0.0.10:8891/mcp"
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

          <CredentialScopePanel
            scope={draft.credential_scope ?? 'bound'}
            ids={draft.credential_scope_ids ?? []}
            onScope={(value) => set('credential_scope', value)}
            onIds={(value) => set('credential_scope_ids', value)}
          />

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

        <aside className="flex flex-col gap-4 xl:sticky xl:top-24">
          {(testConnection.data || testConnection.isPending || testConnection.isError) && (
            <VerifyPanel
              title="Connection test"
              result={testConnection.data ?? null}
              pending={testConnection.isPending}
              error={testConnection.isError ? errorDetail(testConnection.error) : null}
            />
          )}
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
