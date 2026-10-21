import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Service, ServiceType } from './types'

export type CandidateType = 'device' | 'service'
export type CandidateStatus = 'pending' | 'accepted' | 'ignored' | 'expired'

export interface DiscoveredCandidate {
  id: number
  candidate_type: CandidateType
  discovered_via: string
  network_id: number | null
  raw_attributes: Record<string, unknown>
  first_seen_at: string
  last_seen_at: string
  times_seen: number
  status: CandidateStatus
  resulting_device_id: number | null
  resulting_service_id: number | null
}

export function useDiscoveredCandidates() {
  return useQuery({
    queryKey: ['discovery', 'candidates'],
    queryFn: () =>
      api.get<DiscoveredCandidate[]>('/discovery/candidates?status=pending&candidate_type=service'),
    refetchInterval: 10_000,
  })
}

function useInvalidateCandidates() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['discovery', 'candidates'] })
}

export function useAcceptService() {
  const invalidate = useInvalidateCandidates()
  return useMutation({
    mutationFn: ({
      candidateId,
      serviceType,
      name,
      config,
    }: {
      candidateId: number
      serviceType: ServiceType
      name?: string
      config: Record<string, unknown>
    }) =>
      api.post<Service>(`/discovery/candidates/${candidateId}/accept-service`, {
        service_type: serviceType,
        name: name || null,
        config,
      }),
    onSuccess: invalidate,
  })
}

export function useIgnoreCandidate() {
  const invalidate = useInvalidateCandidates()
  return useMutation({
    mutationFn: (candidateId: number) => api.post<void>(`/discovery/candidates/${candidateId}/ignore`),
    onSuccess: invalidate,
  })
}

export interface OuiStatus {
  entry_count: number
  updated_at: string | null
}

export function useOuiStatus() {
  return useQuery({
    queryKey: ['discovery', 'oui-status'],
    queryFn: () => api.get<OuiStatus>('/discovery/oui/status'),
  })
}

export function useUpdateOuiRegistry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<OuiStatus>('/discovery/oui/update'),
    onSuccess: (status) => {
      queryClient.setQueryData(['discovery', 'oui-status'], status)
      // Vendor hints are attached to raw_attributes at observation time, so
      // an updated registry only affects candidates re-observed on the next
      // scan - not a reason to invalidate the current list.
    },
  })
}
