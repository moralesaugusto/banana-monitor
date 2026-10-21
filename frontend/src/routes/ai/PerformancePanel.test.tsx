import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Performance } from '../../api/aiPerformance'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { PerformancePanel } from './PerformancePanel'

const performance: Performance = {
  since: null,
  by_agent: [
    {
      agent: 'sinverguenza', models: ['qwen-big'], calls: 3, errors: 0,
      avg_duration_ms: 5_000, min_duration_ms: 2_000, max_duration_ms: 9_000,
      prompt_tokens: 1_500, completion_tokens: 300, tokens_per_second: 20,
    },
    {
      agent: 'reporter', models: ['qwen-small'], calls: 10, errors: 1,
      avg_duration_ms: 800, min_duration_ms: 400, max_duration_ms: 1_200,
      prompt_tokens: 2_000, completion_tokens: 400, tokens_per_second: 50,
    },
  ],
  by_agent_model: [
    {
      agent: 'sinverguenza', model: 'qwen-big', calls: 3,
      avg_duration_ms: 5_000, min_duration_ms: 2_000, max_duration_ms: 9_000,
      prompt_tokens: 1_500, completion_tokens: 300, tokens_per_second: 20,
    },
    {
      agent: 'reporter', model: 'qwen-small', calls: 10,
      avg_duration_ms: 800, min_duration_ms: 400, max_duration_ms: 1_200,
      prompt_tokens: 2_000, completion_tokens: 400, tokens_per_second: 50,
    },
  ],
  by_model: [
    {
      model: 'qwen-big', agents: ['sinverguenza'], calls: 3,
      avg_duration_ms: 5_000, min_duration_ms: 2_000, max_duration_ms: 9_000,
      prompt_tokens: 1_500, completion_tokens: 300, tokens_per_second: 20,
    },
    {
      model: 'qwen-small', agents: ['reporter'], calls: 10,
      avg_duration_ms: 800, min_duration_ms: 400, max_duration_ms: 1_200,
      prompt_tokens: 2_000, completion_tokens: 400, tokens_per_second: 50,
    },
  ],
}

function renderPanel() {
  render(
    <QueryClientProvider client={queryClient}>
      <PerformancePanel />
    </QueryClientProvider>,
  )
}

describe('PerformancePanel', () => {
  beforeEach(() => queryClient.clear())

  it('shows per-agent and per-model latency, flagging the slowest agent on average', async () => {
    server.use(http.get('/api/ai-mode/performance', () => HttpResponse.json(performance)))
    renderPanel()

    // sinverguenza/reporter each appear twice: their own agent row, and as "Used by" in the model table.
    expect((await screen.findAllByText('sinverguenza')).length).toBeGreaterThan(1)
    expect(screen.getAllByText('reporter').length).toBeGreaterThan(1)
    expect(screen.getAllByText('5.0s').length).toBeGreaterThan(0)
    expect(screen.getAllByText('800ms').length).toBeGreaterThan(0)
    expect(screen.getByText(/Slowest on average:/)).toBeInTheDocument()
    expect(screen.getAllByText('qwen-big').length).toBeGreaterThan(0)
    expect(screen.getAllByText('qwen-small').length).toBeGreaterThan(0)
  })

  it('groups the agent/model breakdown by agent', async () => {
    server.use(http.get('/api/ai-mode/performance', () => HttpResponse.json(performance)))
    renderPanel()

    const heading = await screen.findByRole('heading', { name: 'By agent and model' })
    const section = heading.closest('section')
    expect(section).not.toBeNull()
    // Each agent gets its own sub-heading right above its own small model table.
    expect(within(section!).getByRole('heading', { level: 3, name: 'sinverguenza' })).toBeInTheDocument()
    expect(within(section!).getByRole('heading', { level: 3, name: 'reporter' })).toBeInTheDocument()
  })

  it('shows an empty state with no history yet', async () => {
    server.use(
      http.get('/api/ai-mode/performance', () =>
        HttpResponse.json({ since: null, by_agent: [], by_agent_model: [], by_model: [] }),
      ),
    )
    renderPanel()

    expect(await screen.findByText(/No model calls recorded yet\. Start a run/)).toBeInTheDocument()
    expect(await screen.findAllByText(/No model calls recorded yet\.$/)).toHaveLength(2)
  })

  it('resets the stats with confirmation and shows when it was last reset', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let resetCalled = false
    server.use(
      http.get('/api/ai-mode/performance', () =>
        HttpResponse.json(resetCalled ? { ...performance, since: '2026-10-19T12:00:00Z' } : performance),
      ),
      http.post('/api/ai-mode/performance/reset', () => {
        resetCalled = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: 'Reset stats' }))
    expect(window.confirm).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText(/Counting since the reset on/)).toBeInTheDocument())
  })
})
