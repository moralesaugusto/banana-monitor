import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { AgentsPage } from './AgentsPage'

const agent = (id: number, name: string) => ({
  id, name, role: '', system_prompt: '', base_url: '', model_override: '', temperature: 0.2, max_iterations: 5,
  enabled_tools: [], subscribes: ['task.' + name], publishes: [], require_approval: 'none', enabled: true,
})
const schedule = {
  schedule_enabled: true, schedule_interval_seconds: 3600, schedule_entry_agent: 'discoverer', max_run_minutes: 20,
  max_targets: 25, llm_call_timeout_seconds: 120, last_scheduled_at: null,
  next_run_at: new Date(Date.now() + 3_600_000).toISOString(),
}

function handlers(status: Record<string, unknown>) {
  server.use(
    http.get('/api/ai-mode/agents', () => HttpResponse.json([agent(1, 'discoverer'), agent(2, 'reviewer')])),
    http.get('/api/ai-mode/tools', () => HttpResponse.json({ default_system_prompt: '', tools: [], guardrails: [], allowed_nmap_flags: '' })),
    http.get('/api/ai-mode/custom-tools', () => HttpResponse.json([])),
    http.get('/api/assistant/config', () => HttpResponse.json({ provider: 'ollama', base_url: 'http://x/v1', model: 'm', credential_id: null })),
    http.get('/api/ai-mode/status', () => HttpResponse.json(status)),
  )
}

function renderPage() {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/ai/agents']}>
        <Routes>
          <Route path="/ai/agents" element={<AgentsPage />} />
          <Route path="/ai/agents/:name" element={<AgentsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const list = () => within(screen.getByRole('navigation', { name: 'Agents' }))

describe('agent status and schedule', () => {
  beforeEach(() => queryClient.clear())

  it('shows which agents are working, waiting, and when the run stops by itself', async () => {
    const now = Date.now()
    handlers({
      ai_enabled: true,
      run: { id: 9, started_by: 'schedule', started_at: new Date(now - 60_000).toISOString(), deadline_at: new Date(now + 600_000).toISOString(), paused: false },
      last_run: null,
      agents: [
        { name: 'discoverer', enabled: true, state: 'working', queued: 0 },
        { name: 'reviewer', enabled: true, state: 'waiting', queued: 2 },
      ],
      schedule,
    })
    renderPage()

    expect(await screen.findByText(/Run #9 is running/)).toBeInTheDocument()
    expect(screen.getByText(/started by the schedule/)).toBeInTheDocument()
    expect(screen.getByText(/Stops by itself in/)).toBeInTheDocument()
    expect(list().getByText('Working')).toBeInTheDocument()
    expect(list().getByText('Waiting')).toBeInTheDocument()
    expect(list().getByText('(2 queued)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop now' })).toBeInTheDocument()
  })

  it('shows the next scheduled run when idle, and saves schedule changes', async () => {
    let saved: Record<string, unknown> | null = null
    handlers({
      ai_enabled: true, run: null, last_run: null,
      agents: [
        { name: 'discoverer', enabled: true, state: 'scheduled', queued: 0 },
        { name: 'reviewer', enabled: true, state: 'scheduled', queued: 0 },
      ],
      schedule,
    })
    server.use(
      http.put('/api/ai-mode/schedule', async ({ request }) => {
        saved = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(schedule)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText(/Next scheduled run in/)).toBeInTheDocument()
    expect(list().getAllByText('Scheduled')).toHaveLength(2)

    const limit = screen.getByLabelText('Time limit per run (minutes)')
    await user.clear(limit)
    await user.type(limit, '45')
    await user.click(screen.getByRole('button', { name: 'Save schedule' }))
    await waitFor(() =>
      expect(saved).toMatchObject({
        max_run_minutes: 45,
        schedule_interval_seconds: 3600,
        schedule_enabled: true,
      }),
    )
  })

  it('has a Stop button on a working agent and a Start button on an idle one', async () => {
    const posted: string[] = []
    handlers({
      ai_enabled: true,
      run: { id: 9, started_by: 'manual', started_at: new Date().toISOString(), deadline_at: new Date(Date.now() + 600_000).toISOString(), paused: false },
      last_run: null,
      agents: [
        { name: 'discoverer', enabled: true, state: 'working', queued: 0 },
        { name: 'reviewer', enabled: true, state: 'stopped', queued: 0 },
      ],
      schedule,
    })
    server.use(
      http.post('/api/ai-mode/agents/:id/stop', ({ params }) => {
        posted.push(`stop ${params.id}`)
        return HttpResponse.json({ status: 'stopped' }, { status: 202 })
      }),
      http.post('/api/ai-mode/agents/:id/start', ({ params }) => {
        posted.push(`start ${params.id}`)
        return HttpResponse.json({ status: 'started', run_id: 9 }, { status: 202 })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Stop agent' })) // discoverer is selected first
    await user.click(list().getByText('reviewer'))
    await user.click(await screen.findByRole('button', { name: 'Start agent' })) // run active + stopped: rejoins the run
    await waitFor(() => expect(posted).toEqual(['stop 1', 'start 2']))
  })

  it('offers plain Start for the selected agent when no run is active', async () => {
    handlers({
      ai_enabled: true, run: null, last_run: null,
      agents: [
        { name: 'discoverer', enabled: true, state: 'stopped', queued: 0 },
        { name: 'reviewer', enabled: true, state: 'stopped', queued: 0 },
      ],
      schedule: { ...schedule, schedule_enabled: false, next_run_at: null },
    })
    renderPage()
    expect(await screen.findByRole('button', { name: 'Start' })).toBeEnabled()
  })
})
