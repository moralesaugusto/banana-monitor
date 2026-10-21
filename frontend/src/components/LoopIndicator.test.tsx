import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { server } from '../test/mswServer'
import { TopBar } from './TopBar'

const status = (loop: boolean, aiEnabled = true) =>
  http.get('/api/ai-mode/status', () =>
    HttpResponse.json({
      ai_enabled: aiEnabled, run: null, last_run: null, agents: [],
      schedule: {
        schedule_enabled: loop, schedule_interval_seconds: 300, schedule_entry_agent: 'discoverer',
        max_run_minutes: 30, max_targets: 25, llm_call_timeout_seconds: 120, last_scheduled_at: null, next_run_at: null,
      },
    }),
  )

function renderBar() {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TopBar onMenu={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('top bar loop indicator', () => {
  beforeEach(() => queryClient.clear())

  it('is shown while the discovery loop is on', async () => {
    server.use(status(true))
    renderBar()
    expect(await screen.findByRole('link', { name: 'AI discovery loop is on' })).toHaveAttribute('href', '/ai/workflow')
  })

  it.each([[false, true], [true, false]])('is hidden when loop=%s and AI Mode enabled=%s', async (loop, enabled) => {
    server.use(status(loop, enabled))
    renderBar()
    await screen.findByRole('button', { name: 'Refresh data' })
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByRole('link', { name: 'AI discovery loop is on' })).not.toBeInTheDocument()
  })
})

describe('top bar internet indicator', () => {
  beforeEach(() => queryClient.clear())

  const access = (blocked: boolean, agents: string[]) =>
    http.get('/api/system/internet-access', () => HttpResponse.json({ blocked, agents }))

  it('links to the kill switch in settings while an agent has web tools', async () => {
    server.use(access(false, ['researcher']))
    renderBar()
    expect(await screen.findByRole('link', { name: 'Agent internet access is on' })).toHaveAttribute('href', '/system#internet')
  })

  it('shows the blocked state', async () => {
    server.use(access(true, ['researcher']))
    renderBar()
    expect(await screen.findByRole('link', { name: 'Agent internet access is blocked' })).toBeInTheDocument()
  })

  it('is hidden when no agent has web tools', async () => {
    server.use(access(false, []))
    renderBar()
    await screen.findByRole('button', { name: 'Refresh data' })
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByRole('link', { name: /internet access/ })).not.toBeInTheDocument()
  })
})
