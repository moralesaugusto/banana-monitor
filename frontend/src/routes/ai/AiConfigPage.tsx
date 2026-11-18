import { useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import {
  type AgentProvider,
  type AiModeSettings,
  useAiModeSettings,
  useClearAllAgentMemory,
  useListOllamaModels,
  useTestAgentConnection,
  useUpdateAiModeSettings,
} from '../../api/aiMode'
import {
  type AssistantConfig,
  type AssistantProvider,
  useAssistantConfig,
  useAssistantTools,
  useTestAssistantConnection,
  useUpdateAssistantConfig,
} from '../../api/assistant'
import { ApiError } from '../../api/client'
import {
  type Credential,
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  useUpdateCredential,
} from '../../api/credentials'
import { useInternetAccess, useSetInternetBlocked } from '../../api/system'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { SaveBar } from '../../components/SaveBar'
import { approxTokensToChars, charsToApproxTokens, firstSentence, primaryClasses } from './agentFields'
import { CostPanel } from './CostPanel'
import { isStandaloneApiKey, OpenRouterKeyPicker } from './OpenRouterKeyPicker'
import { PerformancePanel } from './PerformancePanel'
import { VerifyPanel } from './VerifyPanel'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

const secondaryButton =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-60'

const OPENROUTER = { base_url: 'https://openrouter.ai/api/v1', model: 'nvidia/nemotron-3.5-lightning:free' }

type Tab = 'general' | 'discovery' | 'assistant' | 'apikeys' | 'cost' | 'performance'
const TABS: { id: Tab; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'discovery', label: 'Discovery' },
  { id: 'assistant', label: 'Chat assistant' },
  { id: 'apikeys', label: 'API Keys' },
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

/** Moved here from the System > Settings page: an agent-specific control belongs with the rest
 * of an agent's settings, not on the general system page. */
function InternetKillSwitchCard() {
  const { data } = useInternetAccess()
  const setBlocked = useSetInternetBlocked()
  const { hash } = useLocation()
  const loaded = Boolean(data)
  useEffect(() => {
    if (loaded && hash === '#internet') document.getElementById('internet')?.scrollIntoView?.()
  }, [loaded, hash])
  if (!data) return null
  return (
    <Card id="internet" className="p-4">
      <div className="text-sm font-medium text-fg">Agent internet kill switch</div>
      <p className="mt-1 text-xs text-fg-muted">
        While engaged, the web_search and fetch_url tools refuse every call from every agent, immediately,
        including runs in progress. Only you can change it; agents have no tool that reads or writes it.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className={primaryClasses}
          disabled={setBlocked.isPending}
          onClick={() => setBlocked.mutate(!data.blocked)}
        >
          {data.blocked ? 'Re-enable agent internet access' : 'Block all agent internet access'}
        </button>
        <span className="text-xs text-fg-muted">
          {data.blocked ? 'Engaged: agents cannot reach the internet.' : 'Released: agents with web tools can search.'}
        </span>
      </div>
    </Card>
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
  const [costBudget, setCostBudget] = useState(initial.cost_budget_usd)
  const [memory, setMemory] = useState({
    memory_max_entries_per_agent: initial.memory_max_entries_per_agent,
    memory_max_content_chars: initial.memory_max_content_chars,
    memory_max_inject_chars: initial.memory_max_inject_chars,
  })
  const setMemoryField = <K extends keyof typeof memory>(key: K, value: (typeof memory)[K]) => {
    update.reset()
    setMemory((d) => ({ ...d, [key]: value }))
  }
  const [apiKey, setApiKey] = useState('')
  const [credentialId, setCredentialId] = useState(initial.llm_credential_id)
  const [keyError, setKeyError] = useState<string | null>(null)
  const listModels = useListOllamaModels()
  const testConnection = useTestAgentConnection()
  const createCredential = useCreateCredential()
  const clearAllMemory = useClearAllAgentMemory()
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
    let resolvedCredentialId = credentialId
    if (llm.llm_provider === 'openrouter' && apiKey) {
      const credential = await createCredential.mutateAsync({
        label: 'OpenRouter API key (agents)',
        credential_type: 'api_token',
        secret: { token: apiKey },
      })
      resolvedCredentialId = credential.id
      setCredentialId(credential.id)
    }
    if (llm.llm_provider === 'openrouter' && resolvedCredentialId === null) {
      setKeyError('Enter the OpenRouter API key.')
      return
    }
    update.mutate({
      enabled,
      ...llm,
      ...memory,
      cost_budget_usd: costBudget,
      llm_credential_id: llm.llm_provider === 'openrouter' ? resolvedCredentialId : null,
    })
    setApiKey('')
  }
  return (
    <>
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
              API key {credentialId ? '(leave blank to keep current key)' : ''}
              <OpenRouterKeyPicker
                inputClasses={inputClasses}
                credentialId={credentialId}
                onSelectCredential={setCredentialId}
                apiKey={apiKey}
                onChangeApiKey={setApiKey}
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
          <label className="flex flex-col gap-1">
            Cost budget, USD (blank = no budget)
            <input
              type="number"
              min={0}
              step="0.01"
              className={`${inputClasses} w-32`}
              value={costBudget ?? ''}
              onChange={(e) => {
                update.reset()
                setCostBudget(e.target.value === '' ? null : Number(e.target.value))
              }}
            />
            <span className="text-xs text-fg-muted">
              Alert-only: crossing it never stops a run, it only pushes one Telegram notification (Settings
              &gt; Chat assistant has no bearing on this - see the Cost tab).
            </span>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={listModels.isPending}
            className={secondaryButton}
            onClick={() => listModels.mutate({ baseUrl: llm.llm_base_url, provider: llm.llm_provider })}
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
                credential_id: credentialId,
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

      <Card className="p-4">
        <div className="text-sm font-medium">Agent memory</div>
        <p className="mt-1 text-xs text-fg-muted">
          Default limits for the <code className="font-mono">remember</code> checkbox (an agent's Model
          section). An agent's own edit page can override any of these for itself; 0 there means "use this
          default". Sizes are shown as an approximate token count (~4 characters per token - actual counts
          vary by model, this is a budget, not an exact number). See the Memory section on an agent's page
          to view or clear what it has saved.
        </p>
        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            Max notes kept per agent
            <input
              type="number"
              min={1}
              max={500}
              className={`${inputClasses} w-32`}
              value={memory.memory_max_entries_per_agent}
              onChange={(e) => setMemoryField('memory_max_entries_per_agent', Number(e.target.value))}
            />
            <span className="text-xs text-fg-muted">
              Oldest notes are dropped automatically once an agent passes this count (a plain count, not a
              size).
            </span>
          </label>
          <label className="flex flex-col gap-1">
            Max size per note (~tokens)
            <input
              type="number"
              min={5}
              max={1000}
              className={`${inputClasses} w-32`}
              value={charsToApproxTokens(memory.memory_max_content_chars)}
              onChange={(e) => setMemoryField('memory_max_content_chars', approxTokensToChars(Number(e.target.value)))}
            />
            <span className="text-xs text-fg-muted">A note longer than this is truncated when saved.</span>
          </label>
          <label className="flex flex-col gap-1">
            Max total injected per call (~tokens)
            <input
              type="number"
              min={25}
              max={5000}
              className={`${inputClasses} w-32`}
              value={charsToApproxTokens(memory.memory_max_inject_chars)}
              onChange={(e) => setMemoryField('memory_max_inject_chars', approxTokensToChars(Number(e.target.value)))}
            />
            <span className="text-xs text-fg-muted">
              The actual context-window cost of memory: how much of an agent's saved notes (newest first)
              get added to its system prompt on every message it handles.
            </span>
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3 border-t border-line pt-3">
          <button
            type="button"
            disabled={clearAllMemory.isPending}
            className="rounded-control border border-red-500/50 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-500/10 disabled:opacity-50"
            onClick={() =>
              window.confirm('Clear every agent\'s saved memory? This cannot be undone.') && clearAllMemory.mutate()
            }
          >
            Clear all agents' memory
          </button>
          {clearAllMemory.isSuccess && <span className="text-xs text-fg-muted">Cleared.</span>}
          {clearAllMemory.isError && <span className="text-xs text-red-600">Could not clear.</span>}
          <span className="text-xs text-fg-muted">
            Wipes every note for every agent. To clear just one agent, use "Clear all" on its own Memory
            card instead.
          </span>
        </div>
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
    <div className="mt-6">
      <InternetKillSwitchCard />
    </div>
    </>
  )
}

type SafeguardKey = 'cred_allow_unlisted_hosts' | 'cred_no_attempt_limit' | 'cred_trust_new_host_keys' | 'cred_pool_for_updates'

const SAFEGUARDS: { key: SafeguardKey; label: string; risk: string }[] = [
  {
    key: 'cred_allow_unlisted_hosts',
    label: 'Allow trying credentials on hosts outside the inventory and configured networks',
    risk: "An agent could send your stored passwords and keys to any private address it is pointed at, including a machine you do not own. Public addresses stay governed by the public-targets switch above.",
  },
  {
    key: 'cred_no_attempt_limit',
    label: 'Remove the limit of 5 rejected credentials per host',
    risk: 'Repeated wrong credentials can lock accounts and trip fail2ban or intrusion alerts on the target.',
  },
  {
    key: 'cred_trust_new_host_keys',
    label: 'Let agents trust an unseen SSH host key on first use',
    risk: "A password or key is sent before the host's identity is verified, so a machine impersonating the target on your network can capture it.",
  },
  {
    key: 'cred_pool_for_updates',
    label: 'Allow pool credentials for apply_updates',
    risk: 'A credential an agent guessed could be used to install updates on a host. Each call still waits for your approval.',
  },
]

/** Safeguards on agents using stored credentials by themselves. Each is on until ticked here. */
function CredentialSafeguardsCard({
  draft,
  set,
}: {
  draft: Record<SafeguardKey, boolean>
  set: (key: SafeguardKey, value: boolean) => void
}) {
  function toggle(item: (typeof SAFEGUARDS)[number], checked: boolean) {
    if (checked && !window.confirm(`Relax this safeguard?\n\n${item.label}\n\n${item.risk}`)) return
    set(item.key, checked)
  }
  return (
    <Card className="border-red-300 bg-red-50 p-4 dark:border-red-900/50 dark:bg-red-950/30">
      <div className="text-sm font-medium text-red-900 dark:text-red-200">Credential safeguards</div>
      <p className="mt-2 text-xs text-red-800 dark:text-red-300">
        <strong>All of these are on by default and should almost always stay on.</strong> They limit how agents use stored
        credentials on their own (see each agent's Stored credentials setting). Ticking a box removes that protection.
        Agents will send stored passwords and keys to machines: make sure you are authorized to access every host involved,
        because you are responsible for everything an agent does with this, including a model or a prompt injection
        steering it somewhere unintended. Changes are recorded as events.
      </p>
      <p className="mt-2 text-xs text-red-800 dark:text-red-300">
        Always enforced, whatever is ticked: a human approves every apply_updates call, and secrets are never shown in a
        result, trace or log.
      </p>
      <ul className="mt-3 flex flex-col gap-3">
        {SAFEGUARDS.map((item) => (
          <li key={item.key}>
            <label className="flex items-start gap-2 text-sm font-medium text-red-900 dark:text-red-200">
              <input
                type="checkbox"
                className="mt-1"
                checked={draft[item.key]}
                onChange={(e) => toggle(item, e.target.checked)}
              />
              {item.label}
            </label>
            <p className="ml-6 mt-0.5 text-xs text-red-800 dark:text-red-300">{item.risk}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function DiscoveryTab({ initial, update }: { initial: AiModeSettings; update: ReturnType<typeof useUpdateAiModeSettings> }) {
  const [draft, setDraft] = useState({
    allow_undefined_network_scan: initial.allow_undefined_network_scan,
    undefined_scan_max_hosts: initial.undefined_scan_max_hosts,
    allow_public_targets: initial.allow_public_targets,
    cred_allow_unlisted_hosts: initial.cred_allow_unlisted_hosts,
    cred_no_attempt_limit: initial.cred_no_attempt_limit,
    cred_trust_new_host_keys: initial.cred_trust_new_host_keys,
    cred_pool_for_updates: initial.cred_pool_for_updates,
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

      <Card className="border-red-300 bg-red-50 p-4 dark:border-red-900/50 dark:bg-red-950/30">
        <div className="text-sm font-medium text-red-900 dark:text-red-200">Allow public (internet) targets</div>
        <label className="mt-3 flex items-center gap-2 text-sm font-medium text-red-900 dark:text-red-200">
          <input
            type="checkbox"
            checked={draft.allow_public_targets}
            onChange={(e) => set('allow_public_targets', e.target.checked)}
          />
          I understand the risk - allow agents to target publicly routable addresses
        </label>
        <p className="mt-2 text-xs text-red-800 dark:text-red-300">
          <strong>Off by default, and it should almost always stay off.</strong> A single-target tool
          (run_nmap, run_nc, record_service, report_open_ports, submit_http_form, and any custom or
          Tajonaso tool's target/ip/host) normally refuses any address outside your registered networks,
          and refuses a public address unconditionally. Turning this on - together with "Allow scanning
          private ranges outside configured networks" above, which must also be on - lifts that second
          refusal: an agent may then run port scans, banner grabs or form/HTTP requests against a public
          IP address it is given or resolves on its own (for example from a domain name), the same as it
          does on your own LAN.
        </p>
        <p className="mt-2 text-xs text-red-800 dark:text-red-300">
          <strong>This is attack surface on a network that is very likely not yours.</strong> Running
          active security tools (port scans, exploitation attempts, credential attacks) against a host
          you do not own or do not have explicit written authorization to test is unauthorized access in
          most jurisdictions, regardless of intent. You are solely responsible for confirming
          authorization before enabling this, and for everything an agent does with it - including if a
          model decides to test an address on its own, or a prompt injection from a scanned page tricks
          an agent into targeting somewhere else. It does not extend to discover_hosts - sweeping a whole
          public CIDR range is never allowed by this switch.
        </p>
      </Card>

      <CredentialSafeguardsCard draft={draft} set={set} />
    </form>
  )
}

/** The tools the chat assistant actually has, read live from the backend's own tool registry
 * (llm/tools.py's TOOL_SCHEMAS/WRITE_TOOL_NAMES) so this list can't drift from what it can
 * really call. `fullAccess` is the in-progress form value, so toggling the checkbox above
 * updates which write tools show as enabled before Save is even clicked. */
function AssistantToolsCard({ fullAccess }: { fullAccess: boolean }) {
  const { data } = useAssistantTools()
  const tools = data?.tools ?? []
  const readOnly = tools.filter((t) => !t.write)
  const write = tools.filter((t) => t.write)

  function ToolRow({ tool }: { tool: (typeof tools)[number] }) {
    const enabled = tool.write ? fullAccess : true
    return (
      <li className="flex items-start gap-2 text-sm">
        <span className={`mt-0.5 shrink-0 text-xs ${enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-fg-subtle'}`}>
          {enabled ? 'on' : 'off'}
        </span>
        <span className="min-w-0">
          <span className="font-mono">{tool.name}</span>
          <span className="block text-xs text-fg-muted">{firstSentence(tool.description)}</span>
        </span>
      </li>
    )
  }

  return (
    <Card className="p-4">
      <h3 className="text-sm font-medium text-fg">Tools available to it</h3>
      <p className="mt-1 text-xs text-fg-muted">
        Every tool is listed whether or not it's currently usable - "off" means full access would need
        to be turned on above, not that the tool is missing.
      </p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
            Read-only (always on)
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {readOnly.map((t) => (
              <ToolRow key={t.name} tool={t} />
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
            Write (needs full access)
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {write.map((t) => (
              <ToolRow key={t.name} tool={t} />
            ))}
          </ul>
        </div>
      </div>
    </Card>
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
  const [credentialId, setCredentialId] = useState(initial.credential_id ?? null)
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
    let resolvedCredentialId = credentialId
    if (provider === 'openrouter' && apiKey) {
      const credential = await createCredential.mutateAsync({
        label: 'OpenRouter API key',
        credential_type: 'api_token',
        secret: { token: apiKey },
      })
      resolvedCredentialId = credential.id
      setCredentialId(credential.id)
    }
    await updateConfig.mutateAsync({
      provider,
      base_url: baseUrl,
      model,
      credential_id: provider === 'openrouter' ? resolvedCredentialId : null,
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
          its curated safe write actions, listed below. Either way, it can never change any system or
          platform setting - not this page, AI Mode settings, agents, integrations, credentials, or
          networks - and has no delete tools; that boundary is not configurable.
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
      <AssistantToolsCard fullAccess={fullAccess} />
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
              API key {credentialId ? '(leave blank to keep current key)' : ''}
              <OpenRouterKeyPicker
                inputClasses={inputClasses}
                credentialId={credentialId}
                onSelectCredential={setCredentialId}
                apiKey={apiKey}
                onChangeApiKey={setApiKey}
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
              credential_id: credentialId,
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

function NewKeyForm() {
  const [label, setLabel] = useState('')
  const [token, setToken] = useState('')
  const create = useCreateCredential()

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate(
          { label, credential_type: 'api_token', secret: { token } },
          { onSuccess: () => { setLabel(''); setToken('') } },
        )
      }}
    >
      <label className="text-sm">
        Label
        <input
          className={inputClasses}
          placeholder="e.g. OpenRouter - personal"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </label>
      <label className="text-sm">
        Key
        <input
          type="password"
          className={inputClasses}
          placeholder="sk-or-..."
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </label>
      <button type="submit" className={primaryClasses} disabled={create.isPending || !label.trim() || !token.trim()}>
        Add key
      </button>
      {create.isError && <span className="text-sm text-red-600 dark:text-red-400">{create.error.message}</span>}
    </form>
  )
}

function RenameKeyForm({ credential, onDone }: { credential: Credential; onDone: () => void }) {
  const [label, setLabel] = useState(credential.label)
  const update = useUpdateCredential()

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        update.mutate({ id: credential.id, label }, { onSuccess: onDone })
      }}
    >
      <input className={inputClasses} value={label} onChange={(e) => setLabel(e.target.value)} />
      <button type="submit" className={secondaryButton} disabled={update.isPending || !label.trim()}>
        Save name
      </button>
      <button type="button" className={secondaryButton} onClick={onDone}>
        Cancel
      </button>
    </form>
  )
}

function RotateKeyForm({ credential, onDone }: { credential: Credential; onDone: () => void }) {
  const [token, setToken] = useState('')
  const update = useUpdateCredential()

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        update.mutate({ id: credential.id, secret: { token } }, { onSuccess: onDone })
      }}
    >
      <input
        type="password"
        className={inputClasses}
        placeholder="New key value"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <button type="submit" className={secondaryButton} disabled={update.isPending || !token.trim()}>
        Save new key
      </button>
      <button type="button" className={secondaryButton} onClick={onDone}>
        Cancel
      </button>
    </form>
  )
}

function KeyRow({ credential }: { credential: Credential }) {
  const [mode, setMode] = useState<'view' | 'rename' | 'rotate'>('view')
  const remove = useDeleteCredential()
  const [error, setError] = useState<string | null>(null)

  if (mode === 'rename') return <RenameKeyForm credential={credential} onDone={() => setMode('view')} />
  if (mode === 'rotate') return <RotateKeyForm credential={credential} onDone={() => setMode('view')} />

  async function handleDelete() {
    if (!window.confirm(`Delete the key "${credential.label}"? This cannot be undone.`)) return
    setError(null)
    try {
      await remove.mutateAsync(credential.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to delete key.')
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3 last:border-b-0">
      <div className="min-w-0">
        <div className="text-sm font-medium text-fg">{credential.label}</div>
        <div className="text-xs text-fg-muted">
          {credential.used_by.length === 0 ? 'Unused - safe to delete' : credential.used_by.join(', ')}
          {credential.rotated_at && ` - rotated ${new Date(credential.rotated_at).toLocaleDateString()}`}
        </div>
        {error && <div className="text-xs text-red-600 dark:text-red-400">{error}</div>}
      </div>
      <div className="flex shrink-0 gap-2">
        <button type="button" className={secondaryButton} onClick={() => setMode('rename')}>
          Rename
        </button>
        <button type="button" className={secondaryButton} onClick={() => setMode('rotate')}>
          Rotate
        </button>
        <button
          type="button"
          className="rounded-control border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
          disabled={remove.isPending}
          onClick={handleDelete}
        >
          Delete
        </button>
      </div>
    </li>
  )
}

/** A dedicated repository for OpenRouter API keys, separate from the generic Credentials page:
 * add, rename, rotate or delete one from here, and every picker elsewhere in AI Settings (the
 * agents' default, the chat assistant, an individual agent's Custom mode) lists whatever exists
 * here to choose from, instead of only ever accepting a freshly pasted key. */
function ApiKeysTab() {
  const { data: credentials } = useCredentials()
  const keys = (credentials ?? []).filter(isStandaloneApiKey)

  return (
    <div className="mt-4 flex flex-col gap-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium text-fg">OpenRouter API keys</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Stored once here, then picked from a dropdown wherever an OpenRouter key is needed - the agents'
          default (General tab), the chat assistant's own connection, or an individual agent's own key. Tokens
          owned by Telegram or an integration (like Proxmox) are not listed here; use the Credentials page for
          those.
        </p>
        <div className="mt-3">
          <NewKeyForm />
        </div>
      </Card>
      <Card className="overflow-hidden">
        {keys.length === 0 ? (
          <p className="p-4 text-sm text-fg-muted">No OpenRouter keys stored yet.</p>
        ) : (
          <ul>
            {keys.map((c) => (
              <KeyRow key={c.id} credential={c} />
            ))}
          </ul>
        )}
      </Card>
    </div>
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
      {tab === 'apikeys' && <ApiKeysTab />}
      {tab === 'cost' && <CostPanel />}
      {tab === 'performance' && <PerformancePanel />}
    </div>
  )
}
