import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { AuditPage } from './AuditPage'
import { CleanupCard } from './CleanupCard'

const counts = { reports: 3, events: 0, alerts: 2, bus: 5, history: 9, ai_runs: 1, audit: 4 }

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('data clean-up', () => {
  beforeEach(() => queryClient.clear())
  afterEach(() => vi.restoreAllMocks())

  it('cleans one kind of data after confirmation', async () => {
    const deleted: string[] = []
    server.use(
      http.get('/api/maintenance/counts', () => HttpResponse.json(counts)),
      http.delete('/api/maintenance/:target', ({ params }) => {
        deleted.push(String(params.target))
        return HttpResponse.json({ deleted: 3 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderWith(<CleanupCard />)

    await userEvent.click(await screen.findByRole('button', { name: 'Clean Reports' }))
    await waitFor(() => expect(deleted).toEqual(['reports']))
    expect(await screen.findByText('Deleted 3 row(s).')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clean Events' })).toBeDisabled()
  })

  it('does nothing when the confirmation is declined', async () => {
    const deleted: string[] = []
    server.use(
      http.get('/api/maintenance/counts', () => HttpResponse.json(counts)),
      http.delete('/api/maintenance/:target', ({ params }) => {
        deleted.push(String(params.target))
        return HttpResponse.json({ deleted: 0 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderWith(<CleanupCard />)

    await userEvent.click(await screen.findByRole('button', { name: 'Clean Bus' }))
    expect(deleted).toEqual([])
  })

  it('shows the audit log and cleans it separately', async () => {
    let cleaned = false
    server.use(
      http.get('/api/audit', () =>
        HttpResponse.json([
          { id: 1, ts: '2026-10-14T10:00:00Z', actor: 'admin', method: 'PUT', path: '/api/ai-mode/agents/2', status: 200 },
        ]),
      ),
      http.delete('/api/audit', () => {
        cleaned = true
        return HttpResponse.json({ deleted: 1 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderWith(<AuditPage />)

    expect(await screen.findByText('/api/ai-mode/agents/2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clean audit log' }))
    await waitFor(() => expect(cleaned).toBe(true))
  })
})
