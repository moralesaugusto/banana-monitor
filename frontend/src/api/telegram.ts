import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface TelegramConfig {
  enabled: boolean
  token_set: boolean
  chat_ids: number[]
  notify_alerts: boolean
  notify_ai_reports: boolean
}

export type TelegramUpdate = Partial<Omit<TelegramConfig, 'token_set'>> & { bot_token?: string }

export function useTelegramConfig() {
  return useQuery({
    queryKey: ['telegram', 'config'],
    queryFn: () => api.get<TelegramConfig>('/telegram/config'),
  })
}

export function useUpdateTelegramConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TelegramUpdate) => api.put<TelegramConfig>('/telegram/config', payload),
    onSuccess: (config) => queryClient.setQueryData(['telegram', 'config'], config),
  })
}

export function useTelegramTest() {
  return useMutation({ mutationFn: () => api.post<{ sent: number }>('/telegram/test') })
}
