import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface DiscoverySettings {
  nmap_enabled: boolean
  scan_mode: 'manual' | 'auto'
  auto_interval_seconds: number
  timing_template: number
  host_timeout_seconds: number
  max_retries: number
  version_intensity: number
  ai_mode_enabled: boolean
  ssh_hostkey_approval: boolean
  ssh_hostkey_auto_repin: boolean
  auto_accept_services: boolean
  dns_server: string
}

export interface ScanOverview {
  scanning: boolean
  total_hosts: number
  scanned_hosts: number
}

const SETTINGS_KEY = ['system', 'discovery-settings']

export function useDiscoverySettings() {
  return useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: () => api.get<DiscoverySettings>('/system/discovery-settings'),
  })
}

export function useUpdateDiscoverySettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<DiscoverySettings>) =>
      api.put<DiscoverySettings>('/system/discovery-settings', payload),
    onSuccess: (settings) => queryClient.setQueryData(SETTINGS_KEY, settings),
  })
}

export function useScanOverview() {
  return useQuery({
    queryKey: ['system', 'scan-status'],
    queryFn: () => api.get<ScanOverview>('/system/scan-status'),
    refetchInterval: (query) => (query.state.data?.scanning ? 1_000 : 5_000),
  })
}

export function useScanAll() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ status: string }>('/system/scan-all'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['system', 'scan-status'] }),
  })
}

export interface InternetAccess {
  blocked: boolean
  agents: string[]
}

const INTERNET_KEY = ['system', 'internet-access']

export function useInternetAccess() {
  return useQuery({
    queryKey: INTERNET_KEY,
    queryFn: () => api.get<InternetAccess>('/system/internet-access'),
    refetchInterval: 15000,
  })
}

export function useSetInternetBlocked() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (blocked: boolean) => api.put<InternetAccess>('/system/internet-access', { blocked }),
    onSuccess: (status) => queryClient.setQueryData(INTERNET_KEY, status),
  })
}
