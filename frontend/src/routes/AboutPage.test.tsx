import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { AboutPage } from './AboutPage'

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AboutPage />
    </QueryClientProvider>,
  )
}

describe('AboutPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/discovery/oui/status', () => HttpResponse.json({ entry_count: 0, updated_at: null })),
    )
  })

  it('shows the app version and system info', async () => {
    server.use(
      http.get('/api/about', () =>
        HttpResponse.json({
          app_version: '1.0.0',
          python_version: '3.12.13',
          platform: 'Linux-6.12-x86_64',
          hostname: 'homelab',
          https_enabled: true,
          data_dir: 'data',
        }),
      ),
    )

    renderPage()

    expect(await screen.findByText('1.0.0')).toBeInTheDocument()
    expect(screen.getByText('3.12.13')).toBeInTheDocument()
    expect(screen.getByText('homelab')).toBeInTheDocument()
    expect(screen.getByText('enabled')).toBeInTheDocument()
  })

  it('shows the current OUI registry status and can trigger an update', async () => {
    server.use(
      http.get('/api/discovery/oui/status', () =>
        HttpResponse.json({ entry_count: 36000, updated_at: '2026-09-01T00:00:00Z' }),
      ),
      http.get('/api/about', () =>
        HttpResponse.json({
          app_version: '1.0.0',
          python_version: '3.12.13',
          platform: 'Linux',
          hostname: 'homelab',
          https_enabled: true,
          data_dir: 'data',
        }),
      ),
    )
    let updateCalled = false
    server.use(
      http.post('/api/discovery/oui/update', () => {
        updateCalled = true
        return HttpResponse.json({ entry_count: 37000, updated_at: '2026-09-17T00:00:00Z' })
      }),
    )

    renderPage()

    expect(await screen.findByText(/36,000 vendors/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Update vendor database' }))

    await waitFor(() => expect(updateCalled).toBe(true))
    expect(await screen.findByText(/37,000 vendors/)).toBeInTheDocument()
  })

  it('saves the metrics database cap with the Save button in the Storage card header', async () => {
    let saved: Record<string, unknown> | null = null
    server.use(
      http.get('/api/about', () =>
        HttpResponse.json({
          app_version: '1', python_version: '3', platform: 'x', hostname: 'h', https_enabled: true, data_dir: 'data',
          storage: [{ name: 'metrics.db', size_bytes: 1048576 }], max_db_size_mb: 512, security: [],
        }),
      ),
      http.put('/api/system/discovery-settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(saved)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const cap = await screen.findByLabelText('Metrics database cap (MB)')
    await user.clear(cap)
    await user.type(cap, '256')
    const save = screen.getAllByRole('button', { name: 'Save' })[0]
    expect(save.closest('form')!.firstElementChild).toContainElement(save) // the first row of the card
    await user.click(save)
    await waitFor(() => expect(saved).toEqual({ max_db_size_mb: 256 }))
  })

  it('resets AI Mode from the AI subsystem card after confirmation', async () => {
    let resets = 0
    server.use(
      http.get('/api/about', () => HttpResponse.json({})),
      http.post('/api/ai-mode/reset', () => {
        resets += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()

    expect(await screen.findByText('Start from scratch (AI subsystem)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reset AI Mode' }))
    await waitFor(() => expect(resets).toBe(1))
    expect(await screen.findByText('AI Mode is back to its defaults.')).toBeInTheDocument()
  })
})
