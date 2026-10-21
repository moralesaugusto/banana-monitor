import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type EventSeverity = 'info' | 'warning' | 'error'

export interface EventRow {
  id: number
  ts: string
  source: string
  severity: EventSeverity
  category: string
  message: string
  related_entity_type: 'device' | 'service' | 'integration' | null
  related_entity_id: number | null
}

export function useEvents() {
  return useQuery({
    queryKey: ['events'],
    queryFn: () => api.get<EventRow[]>('/events'),
    refetchInterval: 5_000,
  })
}
