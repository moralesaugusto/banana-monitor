import type { Agent, AgentInput, ApprovalMode } from '../../api/aiMode'

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
  subscribes: [],
  publishes: [],
  require_approval: 'none',
  enabled: true,
  allow_changes: false,
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
  return {
    name, display_name, role, system_prompt, base_url, model_override, temperature, max_iterations, enabled_tools,
    subscribes, publishes, require_approval, enabled, allow_changes, provider, credential_id, llm_timeout_seconds,
    max_run_minutes, mcp_url_override, mcp_timeout_seconds,
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

/** Agents that are enabled and listen to `result.<name>`: where this agent's final answer ends up. */
export function readersOf(agent: Agent, all: Agent[]): string[] {
  const topic = `result.${agent.name}`
  return all.filter((a) => a.enabled && a.name !== agent.name && a.subscribes.some((p) => topicMatches(p, topic))).map((a) => a.name)
}

export type ToolGroup = 'discovery' | 'inspection' | 'team' | 'internet' | 'custom'

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
  },
  { id: 'internet', label: 'Internet', members: ['web_search', 'fetch_url', 'virustotal_lookup'] },
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
