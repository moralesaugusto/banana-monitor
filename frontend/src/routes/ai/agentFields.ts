import type { Agent, AgentInput, AgentProvider, AiModeSettings, ApprovalMode } from '../../api/aiMode'

export const inputClasses = 'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1 text-sm'
export const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'
export const primaryClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

export const AGENT_NAME_PATTERN = /^[a-z][a-z0-9_-]{1,29}$/

export function agentNameError(name: string): string | null {
  return AGENT_NAME_PATTERN.test(name)
    ? null
    : 'Name must use lowercase letters, digits, - or _, 2 to 30 characters, starting with a letter.'
}

export const CHARS_PER_TOKEN_ESTIMATE = 4
/** Rough, model-agnostic heuristic (no tokenizer dependency - see docs/decisions.md): memory size
 * settings are enforced in characters internally but shown/edited in the UI as an approximate
 * token count, since that's the unit a context-window budget is actually specified in. */
export const charsToApproxTokens = (chars: number) => Math.round(chars / CHARS_PER_TOKEN_ESTIMATE)
export const approxTokensToChars = (tokens: number) => Math.round(tokens * CHARS_PER_TOKEN_ESTIMATE)

export const APPROVAL_LABELS: Record<ApprovalMode, string> = {
  none: 'Runs freely',
  messages: 'Human approves its messages',
  tools: 'Human approves its tool calls',
  both: 'Human approves messages and tool calls',
}

export const EMPTY: AgentInput = {
  name: '',
  display_name: null,
  role: '',
  system_prompt: '',
  base_url: '',
  provider: '',
  credential_id: null,
  model_override: '',
  temperature: 0.2,
  max_iterations: 10,
  llm_timeout_seconds: 0,
  max_run_minutes: 0,
  enabled_tools: ['publish_message'],
  mcp_url_override: null,
  mcp_timeout_seconds: 0,
  memory_max_entries_override: 0,
  memory_max_content_chars_override: 0,
  memory_max_inject_chars_override: 0,
  subscribes: [],
  publishes: [],
  require_approval: 'none',
  enabled: true,
  allow_changes: false,
  credential_scope: 'bound',
  credential_scope_ids: [],
  fallback_provider: '',
  fallback_base_url: '',
  fallback_model: '',
  fallback_credential_id: null,
}

export const splitList = (text: string) =>
  text
    .split(/[\n,]+/)
    .map((t) => t.trim())
    .filter(Boolean)

/** The editable part of an agent (no id). */
export function toInput(agent: Agent | AgentInput): AgentInput {
  const { name, display_name, role, system_prompt, base_url, model_override, temperature, max_iterations, enabled_tools } = agent
  const { subscribes, publishes, require_approval, enabled, allow_changes, provider, credential_id, mcp_url_override } = agent
  const llm_timeout_seconds = agent.llm_timeout_seconds ?? 0
  const max_run_minutes = agent.max_run_minutes ?? 0
  const mcp_timeout_seconds = agent.mcp_timeout_seconds ?? 0
  const memory_max_entries_override = agent.memory_max_entries_override ?? 0
  const memory_max_content_chars_override = agent.memory_max_content_chars_override ?? 0
  const memory_max_inject_chars_override = agent.memory_max_inject_chars_override ?? 0
  const credential_scope = agent.credential_scope ?? 'bound'
  const credential_scope_ids = agent.credential_scope_ids ?? []
  const fallback_provider = agent.fallback_provider ?? ''
  const fallback_base_url = agent.fallback_base_url ?? ''
  const fallback_model = agent.fallback_model ?? ''
  const fallback_credential_id = agent.fallback_credential_id ?? null
  return {
    name, display_name, role, system_prompt, base_url, model_override, temperature, max_iterations, enabled_tools,
    subscribes, publishes, require_approval, enabled, allow_changes, provider, credential_id, llm_timeout_seconds,
    max_run_minutes, mcp_url_override, mcp_timeout_seconds, memory_max_entries_override, memory_max_content_chars_override,
    memory_max_inject_chars_override, fallback_provider, fallback_base_url, fallback_model, fallback_credential_id,
    credential_scope, credential_scope_ids,
  }
}

/** Port of `topic_matches` in backend/app/llm/bus.py: `*` is one segment, a final `#` is the rest. */
export function topicMatches(pattern: string, topic: string): boolean {
  const p = pattern.split('.')
  const t = topic.split('.')
  for (let i = 0; i < p.length; i++) {
    if (p[i] === '#') return true
    if (i >= t.length || (p[i] !== '*' && p[i] !== t[i])) return false
  }
  return p.length === t.length
}

type ProviderFields = { provider: Agent['provider']; credential_id: Agent['credential_id'] }

/** Which provider this agent actually calls - its own choice, or the agents' default when it
 * hasn't set one. Mirrors the first step of the backend's effective_endpoint (llm/provider.py).
 * Takes just the two fields that matter so it works for both a saved Agent and an in-progress
 * AgentInput draft. */
export function effectiveProvider(agent: ProviderFields, defaults: AiModeSettings | undefined): AgentProvider {
  return (agent.provider || defaults?.llm_provider || 'ollama') as AgentProvider
}

export type ConnectionMode = 'ollama_default' | 'openrouter_default' | 'custom'

type ConnectionFields = Pick<AgentInput, 'provider' | 'base_url' | 'model_override' | 'credential_id'>

/** Which of the three connection choices an agent's stored fields actually represent - the
 * inverse of the three `applyConnectionMode` branches below. A legacy agent saved before this
 * three-way choice existed (blank provider, nothing else set) is read as whichever of the first
 * two currently matches the agents' default provider, so opening Edit shows a sensible radio
 * rather than falling through to Custom with nothing filled in. */
export function connectionMode(agent: ConnectionFields, defaults: AiModeSettings | undefined): ConnectionMode {
  if (agent.base_url || agent.credential_id) return 'custom'
  const provider = agent.provider || defaults?.llm_provider
  if (provider === 'ollama' && !agent.model_override) return 'ollama_default'
  if (provider === 'openrouter') return 'openrouter_default'
  return 'custom'
}

/** Sets exactly the fields each connection choice means, clearing what it overrides. Switching
 * to "existing Ollama" or "existing OpenRouter" pins this agent to that provider from now on -
 * it will not silently follow a later change to the agents' default provider, unlike a legacy
 * blank-provider agent read by `connectionMode` above. */
export function applyConnectionMode(
  mode: ConnectionMode,
  draft: AgentInput,
  defaults: AiModeSettings | undefined,
): AgentInput {
  if (mode === 'ollama_default') {
    return { ...draft, provider: 'ollama', base_url: '', model_override: '', credential_id: null }
  }
  if (mode === 'openrouter_default') {
    return { ...draft, provider: 'openrouter', base_url: '', credential_id: null }
  }
  return { ...draft, provider: draft.provider || defaults?.llm_provider || 'ollama' }
}

/** Human-readable summary of which key (if any) this agent's connection actually uses - the
 * single place that answers "is this agent actually going to work," without opening Edit and
 * reconciling this agent's own fields against the agents' default on a separate page. */
export function keySummary(agent: ProviderFields, defaults: AiModeSettings | undefined): { text: string; warn: boolean } {
  if (effectiveProvider(agent, defaults) !== 'openrouter') return { text: 'Ollama - no key needed', warn: false }
  if (agent.credential_id) return { text: "OpenRouter - this agent's own key", warn: false }
  if (defaults?.llm_credential_id) return { text: "OpenRouter - the agents' default key", warn: false }
  return { text: 'OpenRouter - no key configured', warn: true }
}

/** Agents that are enabled and listen to `result.<name>`: where this agent's final answer ends up. */
export function readersOf(agent: Agent, all: Agent[]): string[] {
  const topic = `result.${agent.name}`
  return all.filter((a) => a.enabled && a.name !== agent.name && a.subscribes.some((p) => topicMatches(p, topic))).map((a) => a.name)
}

export type ToolGroup = 'discovery' | 'inspection' | 'team' | 'internet' | 'knowledge' | 'custom'

export const TOOL_GROUPS: { id: ToolGroup; label: string; members: string[] }[] = [
  {
    id: 'discovery',
    label: 'Network discovery',
    members: ['run_nmap', 'run_nc', 'record_service', 'report_open_ports', 'discover_hosts'],
  },
  {
    id: 'inspection',
    label: 'Host inspection',
    members: ['list_inspect_targets', 'ssh_readonly', 'winrm_readonly', 'proxmox_get', 'http_inspect', 'apply_updates'],
  },
  {
    id: 'team',
    label: 'Team and reports',
    members: ['publish_message', 'get_network_snapshot', 'get_status_delta', 'save_report'],
    // 'remember' deliberately omitted: it's a configuration choice (does this agent keep notes
    // across runs, and how big a budget), not a situational tool - its checkbox and overrides
    // live in the Model panel (AgentEditPage.tsx) instead of this Tools checklist.
  },
  { id: 'internet', label: 'Internet', members: ['web_search', 'fetch_url', 'virustotal_lookup'] },
  { id: 'knowledge', label: 'Knowledge base', members: ['search_knowledge', 'add_knowledge_entry'] },
]

export function groupTools(names: string[]): { id: ToolGroup; label: string; tools: string[] }[] {
  const known = new Set(TOOL_GROUPS.flatMap((g) => g.members))
  const groups = TOOL_GROUPS.map((g) => ({ id: g.id, label: g.label, tools: names.filter((n) => g.members.includes(n)) }))
  groups.push({ id: 'custom', label: 'Custom tools', tools: names.filter((n) => !known.has(n)) })
  return groups.filter((g) => g.tools.length > 0)
}

export const isInternetTool = (name: string) => TOOL_GROUPS.find((g) => g.id === 'internet')!.members.includes(name)

/** First sentence of a tool description, for a one-line hint next to its checkbox ("e.g." is not a full stop). */
export function firstSentence(text: string): string {
  for (const match of text.matchAll(/[.!?](\s|$)/g)) {
    if (!/\b(e\.g|i\.e)$/i.test(text.slice(0, match.index))) return text.slice(0, match.index + 1)
  }
  return text
}
