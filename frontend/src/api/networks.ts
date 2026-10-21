import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { HealthStatus, Network, NetworkCreate } from './types'

export interface NetworkCredentialBinding {
  id: number
  network_id: number
  credential_id: number
  priority: number
  created_at: string
}

export interface AddressCell {
  ip: string
  status: HealthStatus | null
  device_id: number | null
  display_name: string | null
  managed: boolean | null
}

export interface NetworkMap {
  network_id: number
  cidr: string
  total_addresses: number
  truncated: boolean
  addresses: AddressCell[]
  summary: Record<string, number> | null
}

export function useNetworks() {
  return useQuery({
    queryKey: ['networks'],
    queryFn: () => api.get<Network[]>('/networks'),
  })
}

export function useDeleteNetwork() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (networkId: number) => api.delete<void>(`/networks/${networkId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['networks'] })
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      queryClient.invalidateQueries({ queryKey: ['discovery'] })
    },
  })
}

export function useCreateNetwork() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: NetworkCreate) => api.post<Network>('/networks', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['networks'] })
    },
  })
}

export interface ScanStatus {
  network_id: number
  status: 'idle' | 'scanning'
  total_hosts: number
  scanned_hosts: number
  started_at: string | null
  finished_at: string | null
  failed_hosts?: number
  error?: string | null
}

export function useScanNetwork() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (networkId: number) => api.post<{ status: string }>(`/networks/${networkId}/scan`),
    onSuccess: (_data, networkId) => {
      // The scan itself runs as a detached background task - kick an
      // immediate refetch so the status badge flips to "Scanning..." right
      // away instead of waiting for the next poll tick.
      queryClient.invalidateQueries({ queryKey: ['networks', networkId, 'scan-status'] })
    },
  })
}

export function useScanStatus(networkId: number | null) {
  return useQuery({
    queryKey: ['networks', networkId, 'scan-status'],
    queryFn: () => api.get<ScanStatus>(`/networks/${networkId}/scan-status`),
    enabled: networkId !== null,
    // Poll briskly while a scan could plausibly be running - cheap, in-memory
    // endpoint, not worth a websocket/SSE channel for a homelab-scale UI.
    refetchInterval: (query) => (query.state.data?.status === 'scanning' ? 1500 : 5000),
  })
}

export function useNetworkMap(networkId: number | null) {
  return useQuery({
    queryKey: ['networks', networkId, 'map'],
    queryFn: () => api.get<NetworkMap>(`/networks/${networkId}/map`),
    enabled: networkId !== null,
  })
}

export function useNetworkCredentials(networkId: number | null) {
  return useQuery({
    queryKey: ['networks', networkId, 'credentials'],
    queryFn: () => api.get<NetworkCredentialBinding[]>(`/networks/${networkId}/credentials`),
    enabled: networkId !== null,
  })
}

export function useAddNetworkCredential(networkId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { credential_id: number; priority?: number }) =>
      api.post<NetworkCredentialBinding>(`/networks/${networkId}/credentials`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['networks', networkId, 'credentials'] })
    },
  })
}

export function useRemoveNetworkCredential(networkId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (bindingId: number) =>
      api.delete<void>(`/networks/${networkId}/credentials/${bindingId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['networks', networkId, 'credentials'] })
    },
  })
}
