import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface AgentPerformance {
  agent: string
  models: string[]
  calls: number
  errors: number
  avg_duration_ms: number
  min_duration_ms: number
  max_duration_ms: number
  prompt_tokens: number
  completion_tokens: number
  tokens_per_second: number
}

export interface AgentModelPerformance {
  agent: string
  model: string
  calls: number
  avg_duration_ms: number
  min_duration_ms: number
  max_duration_ms: number
  prompt_tokens: number
  completion_tokens: number
  tokens_per_second: number
}

export interface ModelPerformance {
  model: string
  agents: string[]
  calls: number
  avg_duration_ms: number
  min_duration_ms: number
  max_duration_ms: number
  prompt_tokens: number
  completion_tokens: number
  tokens_per_second: number
}

export interface Performance {
  since: string | null
  by_agent: AgentPerformance[]
  by_agent_model: AgentModelPerformance[]
  by_model: ModelPerformance[]
}

export function usePerformance() {
  return useQuery({
    queryKey: ['ai-performance'],
    queryFn: () => api.get<Performance>('/ai-mode/performance'),
    refetchInterval: 15_000,
  })
}

export function useResetPerformance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/ai-mode/performance/reset'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-performance'] }),
  })
}
