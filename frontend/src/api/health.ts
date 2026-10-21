import { useQuery } from '@tanstack/react-query'
import { api } from './client'

interface HealthResponse {
  status: string
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<HealthResponse>('/health'),
    refetchInterval: 15_000,
  })
}
