import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { AlertStateRow } from './alerts'
import type { EventRow } from './events'

export interface StatusCounts {
  up: number
  down: number
  degraded: number
  unknown: number
}

export interface OverviewSummary {
  devices: StatusCounts
  services: StatusCounts
  integrations_ok: number
  integrations_error: number
  firing_alerts: AlertStateRow[]
  recent_events: EventRow[]
}

export function useOverview() {
  return useQuery({
    queryKey: ['overview'],
    queryFn: () => api.get<OverviewSummary>('/overview'),
    refetchInterval: 5_000,
  })
}

export interface HealthBucket {
  hour: string
  devices: number | null
  services: number | null
}

/** Per hour over the last day: the share of checks that succeeded (0 to 1), null when nothing was checked. */
export function useHealthTrend() {
  return useQuery({
    queryKey: ['overview', 'health-trend'],
    queryFn: () => api.get<{ buckets: HealthBucket[] }>('/overview/health-trend'),
    refetchInterval: 60_000,
  })
}
