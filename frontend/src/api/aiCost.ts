import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface UsageTotals {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  max_context_tokens: number
  calls_without_usage: number
}

export interface AgentUsage extends UsageTotals {
  source: string
  agent: string
  models: string[]
}

export interface ModelUsage extends UsageTotals {
  provider: string
  model: string
}

export interface DayUsage {
  day: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
}

export interface Cost {
  since: string | null
  first_day: string | null
  totals: UsageTotals
  by_agent: AgentUsage[]
  by_model: ModelUsage[]
  by_day: DayUsage[]
}

export interface CatalogModel {
  id: string
  name: string
  context_length: number
  usd_per_million_in: number
  usd_per_million_out: number
  tools: boolean
}

export function useCost() {
  return useQuery({ queryKey: ['ai-cost'], queryFn: () => api.get<Cost>('/ai-mode/cost'), refetchInterval: 15_000 })
}

export function useResetCost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/ai-mode/cost/reset'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-cost'] }),
  })
}

/** Loaded on demand: it asks OpenRouter's public model list, which the rest of the page does not need. */
export function useOpenRouterCatalog(enabled: boolean) {
  return useQuery({
    queryKey: ['ai-cost', 'catalog'],
    queryFn: () => api.get<CatalogModel[]>('/ai-mode/cost/openrouter-models'),
    enabled,
    staleTime: 60 * 60 * 1000,
  })
}
