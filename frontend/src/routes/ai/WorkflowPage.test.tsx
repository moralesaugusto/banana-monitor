import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { WorkflowPage } from './WorkflowPage'

const agent = (id: number, name: string, enabled = true) => ({
  id, name, display_name: null, role: `${name} role`, system_prompt: '', base_url: '', model_override: '',
  temperature: 0.2, max_iterations: 5, enabled_tools: [], subscribes: [`task.${name}`], publishes: ['result.#'],
  require_approval: 'none', enabled, allow_changes: false,
})
const schedule = {
  schedule_enabled: false, schedule_interval_seconds: 600, schedule_entry_agent: 'discoverer', max_run_minutes: 20,
  max_targets: 25, llm_call_timeout_seconds: 120, last_scheduled_at: null, next_run_at: null,
}

beforeEach(() => {
  queryClient.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('DOMMatrixReadOnly', class { m22 = 1 })
})

describe('WorkflowPage', () => {
  it('switches an agent off, starts one alone and edits the loop pause', async () => {
    const patches: unknown[] = []
    const starts: string[] = []
    const schedulePuts: unknown[] = []
    server.use(
      http.get('/api/ai-mode/agents', () => HttpResponse.json([agent(1, 'discoverer'), agent(2, 'reviewer')])),
      http.get('/api/ai-mode/status', () =>
        HttpResponse.json({
          ai_enabled: true, run: null, last_run: null, schedule,
          agents: [
            { name: 'discoverer', display_name: null, enabled: true, state: 'stopped', queued: 0 },
            { name: 'reviewer', display_name: null, enabled: true, state: 'stopped', queued: 0 },
          ],
        }),
      ),
      http.patch('/api/ai-mode/agents/:id/workflow', async ({ request }) => {
        patches.push(await request.json())
        return HttpResponse.json(agent(2, 'reviewer', false))
      }),
      http.post('/api/ai-mode/agents/:id/start', ({ params }) => {
        starts.push(String(params.id))
        return HttpResponse.json({ status: 'started', run_id: 1 }, { status: 202 })
      }),
      http.put('/api/ai-mode/schedule', async ({ request }) => {
        schedulePuts.push(await request.json())
        return HttpResponse.json(schedule)
      }),
    )

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkflowPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await userEvent.click(await screen.findByLabelText('reviewer active'))
    await waitFor(() => expect(patches).toEqual([{ enabled: false }]))

    const runButtons = await screen.findAllByText('Run', { selector: 'button' })
    await userEvent.click(runButtons[1])
    await waitFor(() => expect(starts).toEqual(['2']))

    const pause = await screen.findByLabelText('Pause between runs in seconds')
    await userEvent.clear(pause)
    await userEvent.type(pause, '900')
    await userEvent.tab()
    await waitFor(() => expect(schedulePuts).toEqual([{ schedule_interval_seconds: 900 }]))

    await userEvent.click(screen.getByLabelText('Loop on'))
    await waitFor(() => expect(schedulePuts.at(-1)).toEqual({ schedule_enabled: true }))
  })

  it('shows the live activity label for an agent waiting on a model reply', async () => {
    server.use(
      http.get('/api/ai-mode/agents', () => HttpResponse.json([agent(1, 'discoverer')])),
      http.get('/api/ai-mode/status', () =>
        HttpResponse.json({
          ai_enabled: true,
          run: { id: 1, started_by: 'manual', started_at: '2026-01-01T00:00:00Z', deadline_at: '2026-01-01T00:30:00Z', paused: false },
          last_run: null,
          schedule,
          agents: [{ name: 'discoverer', display_name: null, enabled: true, state: 'working', activity: 'llm', queued: 0 }],
        }),
      ),
      http.get('/api/ai-mode/messages', () => HttpResponse.json([])),
    )

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkflowPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByTestId('agent-activity')).toHaveTextContent('Waiting on model reply')
  })

  it('clicking the node title navigates to the agent edit page, without clicking Active or Run', async () => {
    const starts: string[] = []
    const patches: unknown[] = []
    server.use(
      http.get('/api/ai-mode/agents', () => HttpResponse.json([agent(1, 'discoverer')])),
      http.get('/api/ai-mode/status', () =>
        HttpResponse.json({
          ai_enabled: true, run: null, last_run: null, schedule,
          agents: [{ name: 'discoverer', display_name: null, enabled: true, state: 'stopped', queued: 0 }],
        }),
      ),
      http.patch('/api/ai-mode/agents/:id/workflow', async ({ request }) => {
        patches.push(await request.json())
        return HttpResponse.json(agent(1, 'discoverer', false))
      }),
      http.post('/api/ai-mode/agents/:id/start', ({ params }) => {
        starts.push(String(params.id))
        return HttpResponse.json({ status: 'started', run_id: 1 }, { status: 202 })
      }),
    )

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/ai/workflow']}>
          <Routes>
            <Route path="/ai/workflow" element={<WorkflowPage />} />
            <Route path="/ai/agents/:name/edit" element={<div>EDIT PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await userEvent.click(await screen.findByLabelText('discoverer active'))
    await waitFor(() => expect(patches).toEqual([{ enabled: false }]))
    expect(screen.queryByText('EDIT PAGE')).not.toBeInTheDocument()

    await userEvent.click(await screen.findByText('discoverer role'))
    expect(await screen.findByText('EDIT PAGE')).toBeInTheDocument()
  })

  it('renders a legend explaining the node and edge conventions', async () => {
    server.use(
      http.get('/api/ai-mode/agents', () => HttpResponse.json([agent(1, 'discoverer')])),
      http.get('/api/ai-mode/status', () =>
        HttpResponse.json({
          ai_enabled: true, run: null, last_run: null, schedule,
          agents: [{ name: 'discoverer', display_name: null, enabled: true, state: 'stopped', queued: 0 }],
        }),
      ),
    )

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkflowPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Legend:')).toBeInTheDocument()
    expect(screen.getByText(/waiting on the model/)).toBeInTheDocument()
    expect(screen.getByText(/held for approval/)).toBeInTheDocument()
  })
})
