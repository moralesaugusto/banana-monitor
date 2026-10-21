import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { type AgentProvider, type AiModeSettings, useAiModeSettings, useListOllamaModels, useUpdateAiModeSettings } from '../../api/aiMode'
import {
  type AssistantConfig,
  type AssistantProvider,
  useAssistantConfig,
  useTestAssistantConnection,
  useUpdateAssistantConfig,
} from '../../api/assistant'
import { useCreateCredential } from '../../api/credentials'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { SaveBar } from '../../components/SaveBar'
import { CostPanel } from './CostPanel'
import { PerformancePanel } from './PerformancePanel'
import { VerifyPanel } from './VerifyPanel'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

const secondaryButton =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-60'

const OPENROUTER = { base_url: 'https://openrouter.ai/api/v1', model: 'nvidia/nemotron-3.5-lightning:free' }

type Tab = 'general' | 'discovery' | 'assistant' | 'cost' | 'performance'
const TABS: { id: Tab; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'discovery', label: 'Discovery' },
  { id: 'assistant', label: 'Chat assistant' },
  { id: 'cost', label: 'Cost' },
  { id: 'performance', label: 'Performance' },
]

function Tabs({ active, onChange }: { active: Tab; onChange: (tab: Tab) => void }) {
  return (
    <div role="tablist" className="mt-4 flex gap-1 border-b border-line">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
            active === t.id ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

function GeneralTab({ initial, update }: { initial: AiModeSettings; update: ReturnType<typeof useUpdateAiModeSettings> }) {
  const [enabled, setEnabled] = useState(initial.enabled)
  const [llm, setLlm] = useState({
    llm_provider: initial.llm_provider,
    llm_base_url: initial.llm_base_url,
    llm_model: initial.llm_model,
    llm_call_timeout_seconds: initial.llm_call_timeout_seconds,
    ollama_max_concurrent_calls: initial.ollama_max_concurrent_calls,
    openrouter_max_concurrent_calls: initial.openrouter_max_concurrent_calls,
  })
  const [apiKey, setApiKey] = useState('')
  const [keyError, setKeyError] = useState<string | null>(null)
  const listModels = useListOllamaModels()
  const testConnection = useTestAssistantConnection()
  const createCredential = useCreateCredential()
  const setLlmField = <K extends keyof typeof llm>(key: K, value: (typeof llm)[K]) => {
    update.reset()
    setLlm((d) => ({ ...d, [key]: value }))
  }
  // Choosing OpenRouter fills in its endpoint and a model; going back restores the saved Ollama values.
  function changeProvider(next: AgentProvider) {
    update.reset()
    setLlm((d) => {
      if (next === 'openrouter' && d.llm_base_url !== OPENROUTER.base_url) {
        return { ...d, llm_provider: next, llm_base_url: OPENROUTER.base_url, llm_model: OPENROUTER.model }
      }
      if (next === 'ollama' && d.llm_base_url === OPENROUTER.base_url) {
        const saved = initial.llm_provider === 'ollama'
        return {
          ...d,
          llm_provider: next,
          llm_base_url: saved ? initial.llm_base_url : '',
          llm_model: saved ? initial.llm_model : '',
        }
      }
      return { ...d, llm_provider: next }
    })
  }
  async function save() {
    setKeyError(null)
    let credentialId = initial.llm_credential_id
    if (llm.llm_provider === 'openrouter' && apiKey) {
      const credential = await createCredential.mutateAsync({
        label: 'OpenRouter API key (agents)',
        credential_type: 'api_token',
        secret: { token: apiKey },
      })
      credentialId = credential.id
    }
    if (llm.llm_provider === 'openrouter' && credentialId === null) {
      setKeyError('Enter the OpenRouter API key.')
      return
    }
    update.mutate({
      enabled,
      ...llm,
      llm_credential_id: llm.llm_provider === 'openrouter' ? credentialId : null,
    })
    setApiKey('')
  }
  return (
    <form
      id="ai-config-general-form"
      className="mt-4 flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <Card className="p-4">
        <SaveBar
          saving={update.isPending}
          saved={update.isSuccess}
          error={keyError ?? (update.isError ? update.error.message : null)}
          form="ai-config-general-form"
        />
        <label className="mt-3 flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              update.reset()
              setEnabled(e.target.checked)
            }}
          />
          Enable AI Mode
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          Off by default. When off, no run can be started, regardless of which agents are individually enabled.
          Runs only ever touch hosts inside your configured networks, or - for the Master Discoverer's
          discover_hosts tool - private (RFC1918) ranges if the Discovery tab allows it.
        </p>
      </Card>

      <Card className="p-4">
        <div className="text-sm font-medium">Default LLM for agents</div>
        <p className="mt-1 text-xs text-fg-muted">
          The provider, host and model every agent uses unless its own page sets a different one. It is separate from
          the chat assistant, which has its own connection on the Chat assistant tab.
        </p>
        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            Provider
            <select
              className={inputClasses}
              value={llm.llm_provider}
              onChange={(e) => changeProvider(e.target.value as AgentProvider)}
            >
              <option value="ollama">Ollama</option>
              <option value="openrouter">OpenRouter</option>
            </select>
          </label>
          {llm.llm_provider === 'openrouter' && (
            <label className="flex flex-col gap-1">
              API key {initial.llm_credential_id ? '(leave blank to keep current key)' : ''}
              <input
                type="password"
                className={inputClasses}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-or-..."
              />
            </label>
          )}
          <label className="flex flex-col gap-1">
            {llm.llm_provider === 'openrouter' ? 'API base URL' : 'Ollama host'}
            <input
              className={`${inputClasses} font-mono`}
              value={llm.llm_base_url}
              placeholder="http://localhost:11434/v1"
              onChange={(e) => setLlmField('llm_base_url', e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            Model
            <input
              className={`${inputClasses} font-mono`}
              list="agent-default-models"
              value={llm.llm_model}
              onChange={(e) => setLlmField('llm_model', e.target.value)}
            />
            <datalist id="agent-default-models">
              {listModels.data?.models.map((m) => <option key={m} value={m} />)}
            </datalist>
          </label>
          <label className="flex flex-col gap-1">
            Model call timeout (seconds)
            <input
              type="number"
              min={10}
              max={1800}
              className={`${inputClasses} w-32`}
              value={llm.llm_call_timeout_seconds}
              onChange={(e) => setLlmField('llm_call_timeout_seconds', Number(e.target.value))}
            />
            <span className="text-xs text-fg-muted">
              How long one model call may take before it counts as failed. Raise it for a slow model; an agent
              can override it on its own page, and its loop limit sets how many calls one message may use.
            </span>
          </label>
          <label className="flex flex-col gap-1">
            Max concurrent Ollama calls
            <input
              type="number"
              min={1}
              max={16}
              className={`${inputClasses} w-32`}
              value={llm.ollama_max_concurrent_calls}
              onChange={(e) => setLlmField('ollama_max_concurrent_calls', Number(e.target.value))}
            />
            <span className="text-xs text-fg-muted">
              How many agents may have a model call in flight to an Ollama host at once. A single consumer
              GPU serializes requests anyway; raising this just means longer per-call waits.
            </span>
          </label>
          <label className="flex flex-col gap-1">
            Max concurrent OpenRouter calls
            <input
              type="number"
              min={1}
              max={16}
              className={`${inputClasses} w-32`}
              value={llm.openrouter_max_concurrent_calls}
              onChange={(e) => setLlmField('openrouter_max_concurrent_calls', Number(e.target.value))}
            />
            <span className="text-xs text-fg-muted">
              Same cap for OpenRouter - a hosted API that can sustain more concurrent requests than a home GPU.
            </span>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={listModels.isPending}
            className={secondaryButton}
            onClick={() => listModels.mutate(llm.llm_base_url)}
          >
            Load models
          </button>
          <button
            type="button"
            disabled={testConnection.isPending}
            className={secondaryButton}
            onClick={() =>
              testConnection.mutate({
                provider: llm.llm_provider,
                base_url: llm.llm_base_url,
                model: llm.llm_model,
                api_key: apiKey || undefined,
                credential_id: initial.llm_credential_id,
                timeout_seconds: llm.llm_call_timeout_seconds,
              })
            }
          >
            Test connection
          </button>
        </div>
        {listModels.isError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{listModels.error.message}</p>}
        {listModels.data && (
          <p className="mt-2 text-xs text-fg-muted">
            {listModels.data.models.length} model(s) on {listModels.data.base_url}
          </p>
        )}
      </Card>
      {(testConnection.data || testConnection.isPending || testConnection.isError) && (
        <VerifyPanel
          title="Connection test"
          result={testConnection.data ?? null}
          pending={testConnection.isPending}
          error={testConnection.isError ? testConnection.error.message : null}
        />
      )}
    </form>
  )
}

function DiscoveryTab({ initial, update }: { initial: AiModeSettings; update: ReturnType<typeof useUpdateAiModeSettings> }) {
  const [draft, setDraft] = useState({
    allow_undefined_network_scan: initial.allow_undefined_network_scan,
    undefined_scan_max_hosts: initial.undefined_scan_max_hosts,
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => {
    update.reset()
    setDraft((d) => ({ ...d, [key]: value }))
  }
  return (
    <form
      id="ai-config-discovery-form"
      className="mt-4 flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        update.mutate(draft)
      }}
    >
      <Card className="p-4">
        <SaveBar
          title="Finding new hosts"
          description="The Master Discoverer's discover_hosts tool sweeps a whole CIDR for hosts you don't already know about, the same way scanning a network from the Networks page does. Inside a network you've registered this is always allowed. These settings control whether, and how far, it may also sweep ranges you have not registered."
          saving={update.isPending}
          saved={update.isSuccess}
          error={update.isError ? 'Could not save.' : null}
          form="ai-config-discovery-form"
        />
        <label className="mt-3 flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={draft.allow_undefined_network_scan}
            onChange={(e) => set('allow_undefined_network_scan', e.target.checked)}
          />
          Allow scanning private (RFC1918) ranges outside configured networks
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          Off by default. When on, a range that is not a subnet of any configured Network may still be
          swept, but only if it sits entirely inside 10.0.0.0/8, 172.16.0.0/12 or 192.168.0.0/16 - never a
          public range.
        </p>
        <label className="mt-4 flex max-w-xs flex-col text-sm">
          Host limit for those out-of-network sweeps
          <input
            type="number"
            min={1}
            max={1024}
            className={`${inputClasses} w-32`}
            value={draft.undefined_scan_max_hosts}
            onChange={(e) => set('undefined_scan_max_hosts', Number(e.target.value))}
          />
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          Deliberately smaller than a registered network's own 1024-host scan limit, since a range you
          never registered was never vetted.
        </p>
      </Card>
    </form>
  )
}

function AssistantForm({ initial }: { initial: AssistantConfig }) {
  const updateConfig = useUpdateAssistantConfig()
  const createCredential = useCreateCredential()
  const testConnection = useTestAssistantConnection()

  const [provider, setProvider] = useState<AssistantProvider>(initial.provider)
  const [baseUrl, setBaseUrl] = useState(initial.base_url)
  const [model, setModel] = useState(initial.model)
  const [maxToolIterations, setMaxToolIterations] = useState(initial.max_tool_iterations)
  const [timeoutSeconds, setTimeoutSeconds] = useState(initial.llm_timeout_seconds)
  const [fullAccess, setFullAccess] = useState(initial.full_access)
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Choosing OpenRouter fills in its endpoint and a free model that supports tool calls; going back to
  // Ollama restores the saved Ollama values.
  function changeProvider(next: AssistantProvider) {
    if (next === 'openrouter' && baseUrl !== OPENROUTER.base_url) {
      setBaseUrl(OPENROUTER.base_url)
      setModel(OPENROUTER.model)
    } else if (next === 'ollama' && baseUrl === OPENROUTER.base_url) {
      setBaseUrl(initial.provider === 'ollama' ? initial.base_url : '')
      setModel(initial.provider === 'ollama' ? initial.model : '')
    }
    setProvider(next)
  }

  async function handleSave() {
    setError(null)
    let credentialId = initial.credential_id ?? null
    if (provider === 'openrouter' && apiKey) {
      const credential = await createCredential.mutateAsync({
        label: 'OpenRouter API key',
        credential_type: 'api_token',
        secret: { token: apiKey },
      })
      credentialId = credential.id
    }
    await updateConfig.mutateAsync({
      provider,
      base_url: baseUrl,
      model,
      credential_id: provider === 'openrouter' ? credentialId : null,
      max_tool_iterations: maxToolIterations,
      llm_timeout_seconds: timeoutSeconds,
      full_access: fullAccess,
    })
    setApiKey('')
  }

  return (
    <form
      id="ai-config-assistant-form"
      className="mt-4 flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        handleSave().catch((err: Error) => setError(err.message))
      }}
    >
      <Card className="p-4">
        <h3 className="text-sm font-medium text-fg">What the chat assistant can and can't do</h3>
        <p className="mt-1 text-xs text-fg-muted">
          By default it is read-only: it can read current platform state, but no write tool is even
          offered to the model, and one is refused server-side if it tries anyway. Turning on{' '}
          <span className="font-medium text-fg">full access (god mode)</span> below additionally allows
          its curated safe write actions: accept or ignore a discovery candidate, create or update a
          service, update a device, trigger a network scan, and enable or disable an alert rule. Either
          way, it can never change any system or platform setting - not this page, AI Mode settings,
          agents, integrations, credentials, or networks - and has no delete tools; that boundary is not
          configurable.
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm font-medium text-fg">
          <input
            type="checkbox"
            checked={fullAccess}
            onChange={(e) => setFullAccess(e.target.checked)}
          />
          Full access (god mode)
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          {fullAccess
            ? 'On: the assistant may use its write tools, listed above.'
            : 'Off (default): read-only. Save to apply.'}
        </p>
      </Card>
      <Card className="p-4">
        <SaveBar
          title="Chat assistant connection"
          description="The Ollama or OpenRouter host and model used by the chat panel and the Telegram bot. Agents do not use it; their default LLM is set on the General tab."
          saving={updateConfig.isPending || createCredential.isPending}
          error={error}
          form="ai-config-assistant-form"
        />
        <div className="mt-3 flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            Provider
            <select
              className={inputClasses}
              value={provider}
              onChange={(e) => changeProvider(e.target.value as AssistantProvider)}
            >
              <option value="ollama">Ollama</option>
              <option value="openrouter">OpenRouter</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            Base URL
            <input className={inputClasses} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            Model
            <input className={inputClasses} value={model} onChange={(e) => setModel(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            Model calls per chat turn
            <input
              type="number"
              min={1}
              max={40}
              className={`${inputClasses} w-32`}
              value={maxToolIterations}
              onChange={(e) => setMaxToolIterations(Number(e.target.value))}
            />
            <span className="text-xs text-fg-muted">
              Each call may use tools. A turn that needs more than this ends with a "limit reached" note; raise it
              for slower or less decisive models.
            </span>
          </label>
          <label className="flex flex-col gap-1">
            Model call timeout (seconds)
            <input
              type="number"
              min={10}
              max={1800}
              className={`${inputClasses} w-32`}
              value={timeoutSeconds}
              onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
            />
          </label>
          {provider === 'openrouter' && (
            <label className="flex flex-col gap-1">
              API key {initial.credential_id ? '(leave blank to keep current key)' : ''}
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
        <button
          type="button"
          disabled={testConnection.isPending}
          className="mt-4 rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-60"
          onClick={() =>
            testConnection.mutate({
              provider,
              base_url: baseUrl,
              model,
              timeout_seconds: timeoutSeconds,
              ...(apiKey ? { api_key: apiKey } : {}),
            })
          }
        >
          Test connection
        </button>
      </Card>
      {(testConnection.data || testConnection.isPending || testConnection.isError) && (
        <VerifyPanel
          title="Connection test"
          result={testConnection.data ?? null}
          pending={testConnection.isPending}
          error={testConnection.isError ? testConnection.error.message : null}
        />
      )}
    </form>
  )
}

function AssistantTab() {
  const { data: config } = useAssistantConfig()
  return config ? <AssistantForm key={JSON.stringify(config)} initial={config} /> : null
}

export function AiConfigPage() {
  const { data: settings } = useAiModeSettings()
  const update = useUpdateAiModeSettings()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab | null) ?? 'general'

  return (
    <div>
      <PageHeader
        title="Settings"
        description="The global AI Mode on/off switch, the agents' default LLM, where the Master Discoverer may look for new hosts, and the chat assistant's own connection. Each agent's own model, prompt and tools are edited on its own page under Agents."
      />
      <Tabs active={tab} onChange={(t) => setParams(t === 'general' ? {} : { tab: t })} />
      {settings && tab === 'general' && <GeneralTab key={JSON.stringify(settings)} initial={settings} update={update} />}
      {settings && tab === 'discovery' && <DiscoveryTab key={JSON.stringify(settings)} initial={settings} update={update} />}
      {tab === 'assistant' && <AssistantTab />}
      {tab === 'cost' && <CostPanel />}
      {tab === 'performance' && <PerformancePanel />}
    </div>
  )
}
