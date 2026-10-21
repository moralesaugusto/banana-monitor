import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from './client'

export type AgentProvider = 'ollama' | 'openrouter'

export interface AiModeSettings {
  enabled: boolean
  system_prompt: string
  model_override: string
  llm_base_url: string
  llm_model: string
  llm_provider: AgentProvider
  llm_credential_id: number | null
  llm_call_timeout_seconds: number
  max_iterations: number
  temperature: number
  max_targets: number
  enabled_tools: string[]
  allow_undefined_network_scan: boolean
  undefined_scan_max_hosts: number
  ollama_max_concurrent_calls: number
  openrouter_max_concurrent_calls: number
}

export interface ToolInfo {
  name: string
  description: string
  parameters: Record<string, unknown>
  enabled: boolean
}

export interface AiModeTools {
  default_system_prompt: string
  tools: ToolInfo[]
  guardrails: string[]
  allowed_nmap_flags: string
}

export interface AiRunSummary {
  id: number
  started_at: string
  finished_at: string | null
  status: 'running' | 'done' | 'error'
  targets: string[]
  dry_run: boolean
  model: string
  prompt_tokens: number
  completion_tokens: number
  summary: string | null
  error: string | null
  step_count: number
  services_recorded: number
  paused?: boolean
  started_by?: 'manual' | 'schedule'
  stop_reason?: 'manual' | 'time_limit' | null
  entry_agent?: string
}

export interface AiRunStep {
  idx: number
  ts: string
  kind: 'llm' | 'tool' | 'error'
  name: string | null
  agent?: string | null
  request: unknown
  response: unknown
  duration_ms: number
  prompt_tokens: number
  completion_tokens: number
}

export interface AiRunDetail extends AiRunSummary {
  base_url: string
  system_prompt: string
  settings_snapshot: Record<string, unknown>
  steps: AiRunStep[]
}

export function useAiModeSettings() {
  return useQuery({
    queryKey: ['ai-mode', 'settings'],
    queryFn: () => api.get<AiModeSettings>('/ai-mode/settings'),
  })
}

export function useUpdateAiModeSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<AiModeSettings>) => api.put<AiModeSettings>('/ai-mode/settings', payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(['ai-mode', 'settings'], settings)
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'tools'] })
    },
  })
}

export function useResetAiMode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/ai-mode/reset', {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-mode'] }),
  })
}

export function useAiModeTools() {
  return useQuery({ queryKey: ['ai-mode', 'tools'], queryFn: () => api.get<AiModeTools>('/ai-mode/tools') })
}

export function useAiRuns() {
  return useQuery({
    queryKey: ['ai-mode', 'runs'],
    queryFn: () => api.get<AiRunSummary[]>('/ai-mode/runs'),
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === 'running') ? 2_000 : 10_000),
  })
}

export function useAiRun(id: number | undefined) {
  return useQuery({
    queryKey: ['ai-mode', 'run', id],
    queryFn: () => api.get<AiRunDetail>(`/ai-mode/runs/${id}`),
    enabled: id !== undefined,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1_500 : false),
  })
}

export function useStartAiRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { targets: string[]; dry_run: boolean; entry_agent?: string; message?: string | null }) =>
      api.post<AiRunSummary>('/ai-mode/runs', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-mode', 'runs'] }),
  })
}

export interface CustomTool {
  id: number
  name: string
  description: string
  kind: 'command' | 'mcp'
  command: string[]
  mcp_url: string | null
  mcp_tool: string | null
  parameters: Record<string, unknown>
  enabled: boolean
}
export type CustomToolInput = Omit<CustomTool, 'id'>

export interface Guardrail {
  id: number
  name: string
  description: string
  kind: 'deny_regex' | 'allow_regex'
  pattern: string
  enabled: boolean
}
export type GuardrailInput = Omit<Guardrail, 'id'>

function useCrud<T extends { id: number }, I>(path: string, key: string) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['ai-mode', key] })
    queryClient.invalidateQueries({ queryKey: ['ai-mode', 'settings'] })
  }
  return {
    list: useQuery({ queryKey: ['ai-mode', key], queryFn: () => api.get<T[]>(path) }),
    save: useMutation({
      mutationFn: ({ id, input }: { id?: number; input: I }) =>
        id === undefined ? api.post<T>(path, input) : api.put<T>(`${path}/${id}`, input),
      onSuccess: invalidate,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.delete<void>(`${path}/${id}`), onSuccess: invalidate }),
  }
}

export const useCustomTools = () => useCrud<CustomTool, CustomToolInput>('/ai-mode/custom-tools', 'custom-tools')
export const useGuardrails = () => useCrud<Guardrail, GuardrailInput>('/ai-mode/guardrails', 'guardrails')

// --- Multi-agent: agents, the message bus, human-in-the-loop ----------------------

export type ApprovalMode = 'none' | 'messages' | 'tools' | 'both'

export interface Agent {
  id: number
  name: string
  display_name: string | null
  role: string
  system_prompt: string
  base_url: string
  provider: AgentProvider | ''
  credential_id: number | null
  model_override: string
  temperature: number
  max_iterations: number
  llm_timeout_seconds?: number
  max_run_minutes?: number
  enabled_tools: string[]
  mcp_url_override: string | null
  mcp_timeout_seconds: number
  subscribes: string[]
  publishes: string[]
  require_approval: ApprovalMode
  enabled: boolean
  allow_changes: boolean
  workflow_x?: number | null
  workflow_y?: number | null
}
export type AgentInput = Omit<Agent, 'id'>

/** The label to show a human; `name` is the stable identifier other settings (schedule, manual run) refer to. */
export function agentLabel(agent: { name: string; display_name?: string | null }): string {
  return agent.display_name || agent.name
}

export const useAgents = () => useCrud<Agent, AgentInput>('/ai-mode/agents', 'agents')

export type VerifyStatus = 'ok' | 'info' | 'warn' | 'fail'
export interface VerifyCheck {
  id: string
  status: VerifyStatus
  title: string
  detail: string
}
export interface VerifyResult {
  ok: boolean
  checks: VerifyCheck[]
}

/** Pre-flight checks of an agent's settings (saved or not): tools, Ollama host and model, readers, prerequisites. */
export function useVerifyAgent() {
  return useMutation({
    mutationFn: ({ input, agentId }: { input: AgentInput; agentId?: number }) =>
      api.post<VerifyResult>(`/ai-mode/agents/verify${agentId === undefined ? '' : `?agent_id=${agentId}`}`, input),
  })
}

export interface BusMessage {
  id: number
  run_id: number
  ts: string
  topic: string
  sender: string
  payload: { text?: string; [key: string]: unknown }
  correlation_id: string
  reply_to: string | null
  hops: number
  status: 'delivered' | 'held' | 'rejected' | 'approved'
  note: string | null
  deliveries: { recipient: string; state: 'pending' | 'delivered' | 'acked' | 'rejected' | 'dropped' }[]
}

export function useMessages(runId: number | undefined, filter: { topic?: string; allRuns?: boolean } = {}) {
  const { topic, allRuns = false } = filter
  return useQuery({
    queryKey: ['ai-mode', 'messages', runId, topic, allRuns],
    queryFn: () => {
      const params = new URLSearchParams()
      if (!allRuns) params.set('run_id', String(runId))
      if (topic) params.set('topic', topic)
      return api.get<BusMessage[]>(`/ai-mode/messages?${params}`)
    },
    enabled: runId !== undefined || allRuns,
    refetchInterval: 3_000,
  })
}

/** Server-sent events tell us something happened on the bus; we refetch the log, which stays the source of truth. */
export function useBusEvents() {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const source = new EventSource('/api/ai-mode/events')
    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'messages'] })
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'runs'] })
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'status'] })
    }
    return () => source.close()
  }, [queryClient])
}

export function useMessageActions() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['ai-mode', 'messages'] })
  return {
    approve: useMutation({
      mutationFn: ({ id, payload }: { id: number; payload?: Record<string, unknown> }) =>
        api.post(`/ai-mode/messages/${id}/approve`, { payload: payload ?? null }),
      onSuccess: refresh,
    }),
    reject: useMutation({
      mutationFn: ({ id, reason }: { id: number; reason: string }) =>
        api.post(`/ai-mode/messages/${id}/reject`, { reason }),
      onSuccess: refresh,
    }),
    send: useMutation({
      mutationFn: (body: { run_id: number; topic: string; text: string; correlation_id?: string }) =>
        api.post<BusMessage>('/ai-mode/messages', body),
      onSuccess: refresh,
    }),
  }
}

export function useRunControl() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['ai-mode', 'runs'] })
  const useAction = (action: 'pause' | 'resume' | 'stop') =>
    useMutation({ mutationFn: (runId: number) => api.post(`/ai-mode/runs/${runId}/${action}`, {}), onSuccess: refresh })
  return { pause: useAction('pause'), resume: useAction('resume'), stop: useAction('stop') }
}

/** Asks an Ollama host which models it serves; empty host means the agents' default host. */
export function useListOllamaModels() {
  return useMutation({
    mutationFn: (baseUrl: string) =>
      api.get<{ base_url: string; models: string[] }>(`/ai-mode/ollama-models?base_url=${encodeURIComponent(baseUrl)}`),
  })
}

// --- Schedule, time limits and live agent status ------------------------------------

export interface Schedule {
  schedule_enabled: boolean
  schedule_interval_seconds: number
  schedule_entry_agent: string
  max_run_minutes: number
  max_targets: number
  llm_call_timeout_seconds: number
  last_scheduled_at: string | null
  next_run_at: string | null
}

export type AgentStateName = 'working' | 'waiting' | 'paused' | 'scheduled' | 'stopped' | 'disabled'
export type AgentActivity = 'llm' | 'tool' | 'held' | null

export interface AiStatus {
  ai_enabled: boolean
  run: { id: number; started_by: 'manual' | 'schedule'; started_at: string; deadline_at: string; paused: boolean } | null
  last_run: AiRunSummary | null
  agents: {
    name: string
    display_name: string | null
    enabled: boolean
    state: AgentStateName
    activity: AgentActivity
    queued: number
  }[]
  schedule: Schedule
}

export function useAiStatus() {
  return useQuery({
    queryKey: ['ai-mode', 'status'],
    queryFn: () => api.get<AiStatus>('/ai-mode/status'),
    refetchInterval: 3_000,
  })
}

export function useUpdateSchedule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<Omit<Schedule, 'last_scheduled_at' | 'next_run_at'>>) =>
      api.put<Schedule>('/ai-mode/schedule', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-mode'] }),
  })
}

/** Start or stop one agent. Idle: Start begins a run with that agent first. During a run: Stop removes only that
 * agent, Start brings a stopped one back. */
export function useAgentControl() {
  const queryClient = useQueryClient()
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['ai-mode'] })
  }
  return {
    start: useMutation({
      mutationFn: ({
        agentId,
        targets = [],
        message = null,
      }: { agentId: number; targets?: string[]; message?: string | null }) =>
        api.post<{ status: string; run_id: number }>(`/ai-mode/agents/${agentId}/start`, { targets, message }),
      onSuccess: refresh,
    }),
    stop: useMutation({
      mutationFn: (agentId: number) => api.post<{ status: string }>(`/ai-mode/agents/${agentId}/stop`, {}),
      onSuccess: refresh,
    }),
  }
}

/** Canvas edits: move a node, or switch an agent on or off, without resending its whole configuration. */
export function useUpdateAgentWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: number; enabled?: boolean; workflow_x?: number; workflow_y?: number }) =>
      api.patch<Agent>(`/ai-mode/agents/${id}/workflow`, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'agents'] })
      queryClient.invalidateQueries({ queryKey: ['ai-mode', 'status'] })
    },
  })
}

// --- Bus visibility ---------------------------------------------------------------

export interface BusParty {
  agent: string
  enabled: boolean
  pattern: string
}
export interface BusRoute {
  topic: string
  valid: boolean
  subscribers: BusParty[]
  publishers: BusParty[]
}
export interface BusTopicStats {
  topic: string
  messages: number
  held: number
  last_ts: string
  publishers: string[]
  recipients: string[]
  deliveries: Record<string, number>
}
export interface BusOverview {
  run_id: number | null
  total_messages: number
  topics: BusTopicStats[]
}

/** The server's own answer to "who would receive a message on this topic", from the matcher the bus uses. */
export function useBusRoute(topic: string) {
  return useQuery({
    queryKey: ['ai-mode', 'bus-route', topic],
    queryFn: () => api.get<BusRoute>(`/ai-mode/bus/route?topic=${encodeURIComponent(topic)}`),
    enabled: topic.trim() !== '',
  })
}

/** Per-topic traffic for one run, or for every run when `runId` is null. */
export function useBusOverview(runId: number | null) {
  return useQuery({
    queryKey: ['ai-mode', 'bus-overview', runId],
    queryFn: () => api.get<BusOverview>(`/ai-mode/bus/overview${runId === null ? '' : `?run_id=${runId}`}`),
    placeholderData: keepPreviousData,
    refetchInterval: 5_000,
  })
}

export interface BusGauge {
  used: number
  limit: number | null
}
export interface BusHealth {
  run_id: number
  active: boolean
  messages: BusGauge
  hops: BusGauge
  seconds: BusGauge
  approval_timeout_seconds: number
  agents: { name: string; queued: number; working: boolean; held: number; dropped: number }[]
  held: { message_id: number; topic: string; sender: string; ts: string; age_seconds: number; overdue: boolean }[]
  problems: {
    kind: 'dropped' | 'rejected'
    message_id: number
    topic: string
    sender: string
    recipient: string | null
    reason: string
    ts: string
  }[]
}

/** How close a run is to its limits, and what is stuck or was discarded. */
export function useBusHealth(runId: number | undefined) {
  return useQuery({
    queryKey: ['ai-mode', 'bus-health', runId],
    queryFn: () => api.get<BusHealth>(`/ai-mode/bus/health?run_id=${runId}`),
    enabled: runId !== undefined,
    placeholderData: keepPreviousData,
    refetchInterval: 3_000,
  })
}
