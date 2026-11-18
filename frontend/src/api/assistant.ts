import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
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

export interface AssistantToolInfo {
  name: string
  description: string
  parameters: Record<string, unknown>
  write: boolean
  enabled: boolean
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

export function useAssistantTools() {
  return useQuery({
    queryKey: ['assistant', 'tools'],
    queryFn: () => api.get<{ tools: AssistantToolInfo[] }>('/assistant/tools'),
  })
}

export function useUpdateAssistantConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AssistantConfigUpdate) => api.put<AssistantConfig>('/assistant/config', payload),
    onSuccess: (config) => {
      queryClient.setQueryData(CONFIG_KEY, config)
      queryClient.invalidateQueries({ queryKey: ['assistant', 'tools'] }) // full_access changes which are enabled
    },
  })
}

export function useAssistantMessages() {
  return useQuery({
    queryKey: MESSAGES_KEY,
    queryFn: () => api.get<AssistantMessage[]>('/assistant/messages'),
  })
}

/**
 * Streams one chat turn over SSE: `onDelta` fires for each content token of the turn's final
 * answer as it arrives (nothing fires during a tool-calling iteration - see
 * backend/app/llm/service.py's module docstring for why). Resolves with the persisted reply once
 * the stream ends, or rejects on a `{"error": ...}` event or a network failure.
 */
async function streamChatMessage(
  message: string,
  onDelta: (text: string) => void,
): Promise<AssistantMessage> {
  const response = await fetch('/api/assistant/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!response.ok || !response.body) {
    throw new Error(`Assistant stream failed: ${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AssistantMessage | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const event = JSON.parse(line.slice('data: '.length)) as
        | { delta: string }
        | { message: AssistantMessage }
        | { error: string }
      if ('delta' in event) onDelta(event.delta)
      else if ('message' in event) result = event.message
      else throw new Error(event.error)
    }
  }
  if (!result) throw new Error('Assistant stream ended with no reply')
  return result
}

/** Drives one chat turn via SSE: `streamingText` grows live as the reply's content arrives, then
 * resets to null once the turn is persisted and the message list is refetched. */
export function useStreamChatMessage() {
  const queryClient = useQueryClient()
  const [streamingText, setStreamingText] = useState<string | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  async function send(message: string) {
    setIsPending(true)
    setIsError(false)
    setStreamingText('')
    try {
      await streamChatMessage(message, (delta) => setStreamingText((prev) => (prev ?? '') + delta))
      queryClient.invalidateQueries({ queryKey: MESSAGES_KEY })
    } catch {
      setIsError(true)
    } finally {
      setIsPending(false)
      setStreamingText(null)
    }
  }

  return { send, streamingText, isPending, isError }
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
