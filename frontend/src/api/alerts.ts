import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type AlertConditionType =
  | 'device_down'
  | 'service_down'
  | 'high_cpu'
  | 'high_memory'
  | 'disk_usage_high'
  | 'integration_failing'
  | 'metric_threshold'

export const ALERT_CONDITION_TYPES: AlertConditionType[] = [
  'device_down',
  'service_down',
  'high_cpu',
  'high_memory',
  'disk_usage_high',
  'integration_failing',
  'metric_threshold',
]

export type AlertSeverity = 'critical' | 'warning' | 'info'
export type AlertState = 'ok' | 'pending' | 'firing' | 'resolved' | 'flapping'

export interface AlertRule {
  id: number
  name: string
  condition_type: AlertConditionType
  entity_selector: Record<string, unknown>
  parameters: Record<string, unknown>
  severity: AlertSeverity
  enabled: boolean
  flap_dampening: Record<string, unknown>
}

export interface AlertRuleCreate {
  name: string
  condition_type: AlertConditionType
  entity_selector?: Record<string, unknown>
  parameters?: Record<string, unknown>
  severity?: AlertSeverity
  enabled?: boolean
}

export interface AlertStateRow {
  id: number
  alert_rule_id: number
  entity_type: 'device' | 'service' | 'integration'
  entity_id: number
  state: AlertState
  state_changed_at: string
  last_evaluated_at: string | null
  current_value: number | null
  consecutive_breach_count: number
  flap_score: number
}

export function useAlertRules() {
  return useQuery({
    queryKey: ['alert-rules'],
    queryFn: () => api.get<AlertRule[]>('/alerts/rules'),
  })
}

export function useCreateAlertRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AlertRuleCreate) => api.post<AlertRule>('/alerts/rules', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
}

export function useUpdateAlertRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.patch<AlertRule>(`/alerts/rules/${id}`, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
}

export function useDeleteAlertRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/alerts/rules/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
}

export function useAlertStates() {
  return useQuery({
    queryKey: ['alert-states'],
    queryFn: () => api.get<AlertStateRow[]>('/alerts/states'),
    refetchInterval: 5_000,
  })
}
