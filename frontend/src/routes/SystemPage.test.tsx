import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { MemoryRouter } from 'react-router-dom'
import { SystemPage } from './SystemPage'

const settings = {
  nmap_enabled: true,
  scan_mode: 'auto',
  auto_interval_seconds: 1800,
  timing_template: 4,
  host_timeout_seconds: 30,
  max_retries: 1,
  version_intensity: 5,
  ai_mode_enabled: false,
  ssh_hostkey_approval: true,
  ssh_hostkey_auto_repin: true,
  dns_server: '',
}

describe('SystemPage', () => {
  beforeEach(() => {
    queryClient.clear()
    server.use(
      http.get('/api/system/discovery-settings', () => HttpResponse.json(settings)),
      http.get('/api/system/scan-status', () =>
        HttpResponse.json({ scanning: false, total_hosts: 0, scanned_hosts: 0 }),
      ),
    )
  })

  function renderPage() {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SystemPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('saves a changed scan mode and starts a scan', async () => {
    let saved: Record<string, unknown> | null = null
    let scanned = false
    server.use(
      http.put('/api/system/discovery-settings', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...settings, ...saved })
      }),
      http.post('/api/system/scan-all', () => {
        scanned = true
        return HttpResponse.json({ status: 'scan started' }, { status: 202 })
      }),
    )
    renderPage()
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText('Scan mode'), 'manual')
    expect(saved).toBeNull() // nothing is sent until Save is pressed
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved).toMatchObject({ scan_mode: 'manual' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Scan all networks now' }))
    await waitFor(() => expect(scanned).toBe(true))
  })

  it('saves the Telegram token and chat ids without showing the token back', async () => {
    let body: Record<string, unknown> = {}
    server.use(
      http.get('/api/telegram/config', () =>
        HttpResponse.json({
          enabled: false, token_set: false, chat_ids: [], notify_alerts: true, notify_ai_reports: true,
        }),
      ),
      http.put('/api/telegram/config', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          enabled: false, token_set: true, chat_ids: [42], notify_alerts: true, notify_ai_reports: true,
        })
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SystemPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(await screen.findByPlaceholderText('From @BotFather'), '123:abc')
    await userEvent.type(screen.getByPlaceholderText('123456789'), '42')
    const saveButtons = screen.getAllByRole('button', { name: 'Save' })
    await userEvent.click(saveButtons[saveButtons.length - 1])
    await waitFor(() => expect(body).toMatchObject({ bot_token: '123:abc', chat_ids: [42] }))
    await waitFor(() => expect(screen.getByPlaceholderText('From @BotFather')).toHaveValue(''))
  })

  it('turns off automatic Telegram push for AI-generated reports', async () => {
    let body: Record<string, unknown> = {}
    server.use(
      http.get('/api/telegram/config', () =>
        HttpResponse.json({
          enabled: true, token_set: true, chat_ids: [42], notify_alerts: true, notify_ai_reports: true,
        }),
      ),
      http.put('/api/telegram/config', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          enabled: true, token_set: true, chat_ids: [42], notify_alerts: true, notify_ai_reports: false,
        })
      }),
    )
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SystemPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const toggle = await screen.findByRole('checkbox', {
      name: 'Send AI-generated reports to these chats automatically',
    })
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)

    await waitFor(() => expect(body).toMatchObject({ notify_ai_reports: false }))
  })
})
