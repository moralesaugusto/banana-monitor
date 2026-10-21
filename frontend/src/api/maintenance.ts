import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type CleanTarget = 'reports' | 'events' | 'alerts' | 'bus' | 'history' | 'ai-runs'

export interface CleanCounts {
  reports: number
  events: number
  alerts: number
  bus: number
  history: number
  ai_runs: number
  audit: number
}

export interface AuditEntry {
  id: number
  ts: string
  actor: string
  method: string
  path: string
  status: number
}

export function useCleanCounts() {
  return useQuery({ queryKey: ['maintenance', 'counts'], queryFn: () => api.get<CleanCounts>('/maintenance/counts') })
}

export function useClean() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (target: CleanTarget) => api.delete<{ deleted: number }>(`/maintenance/${target}`),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useAuditLog() {
  return useQuery({ queryKey: ['audit'], queryFn: () => api.get<AuditEntry[]>('/audit?limit=500') })
}

export function useCleanAudit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<{ deleted: number }>('/audit'),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}
