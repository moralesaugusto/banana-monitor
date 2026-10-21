import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface AboutInfo {
  app_version: string
  python_version: string
  platform: string
  hostname: string
  https_enabled: boolean
  data_dir: string
  storage?: { name: string; size_bytes: number }[]
  max_db_size_mb?: number
  security?: { label: string; value: string; ok: boolean | null; detail: string | null }[]
}

export function useAbout() {
  return useQuery({
    queryKey: ['about'],
    queryFn: () => api.get<AboutInfo>('/about'),
  })
}

export function useSetMaxDbSize() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (max_db_size_mb: number) => api.put('/system/discovery-settings', { max_db_size_mb }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['about'] }),
  })
}

export function useResetInventory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ devices: number; services: number }>('/system/reset', { confirm: 'RESET' }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}
