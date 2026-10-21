import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { VerifyResult } from './aiMode'
import { api } from './client'

export type AssistantProvider = 'ollama' | 'openrouter'

export interface AssistantConfig {
  provider: AssistantProvider
  base_url: string
  model: string
  credential_id: number | null
  max_tool_iterations: number
  llm_timeout_seconds: number
  full_access: boolean
}

export interface AssistantConfigUpdate {
  provider?: AssistantProvider
  base_url?: string
  model?: string
  credential_id?: number | null
  max_tool_iterations?: number
  llm_timeout_seconds?: number
  full_access?: boolean
}

export interface ToolCallRecord {
  name: string
  arguments: Record<string, unknown>
  result: unknown
}

export interface AssistantMessage {
  id: number
  ts: string
  role: 'user' | 'assistant'
  content: string
  tool_calls: ToolCallRecord[] | null
}

const MESSAGES_KEY = ['assistant', 'messages']
const CONFIG_KEY = ['assistant', 'config']

export function useAssistantConfig() {
  return useQuery({
    queryKey: CONFIG_KEY,
    queryFn: () => api.get<AssistantConfig>('/assistant/config'),
  })
}

export function useUpdateAssistantConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AssistantConfigUpdate) => api.put<AssistantConfig>('/assistant/config', payload),
    onSuccess: (config) => {
      queryClient.setQueryData(CONFIG_KEY, config)
    },
  })
}

export function useAssistantMessages() {
  return useQuery({
    queryKey: MESSAGES_KEY,
    queryFn: () => api.get<AssistantMessage[]>('/assistant/messages'),
  })
}

export function useSendChatMessage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (message: string) => api.post<{ reply: AssistantMessage }>('/assistant/chat', { message }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MESSAGES_KEY })
    },
  })
}

export function useClearAssistantMessages() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<void>('/assistant/messages'),
    onSuccess: () => {
      queryClient.setQueryData(MESSAGES_KEY, [])
    },
  })
}

export interface ConnectionTestInput {
  provider: AssistantProvider
  base_url: string
  model: string
  api_key?: string
  credential_id?: number | null
  timeout_seconds?: number
}

/** Tries the connection with the values in the form, saved or not. A typed key is used once, never stored. */
export function useTestAssistantConnection() {
  return useMutation({ mutationFn: (input: ConnectionTestInput) => api.post<VerifyResult>('/assistant/test', input) })
}
