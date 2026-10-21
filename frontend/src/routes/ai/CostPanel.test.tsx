import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Cost } from '../../api/aiCost'
import { queryClient } from '../../lib/queryClient'
import { server } from '../../test/mswServer'
import { CostPanel, estimate } from './CostPanel'

const cost: Cost = {
  since: null,
  first_day: '2026-10-14',
  totals: {
    calls: 6,
    prompt_tokens: 4_700,
    completion_tokens: 180,
    total_tokens: 4_880,
    max_context_tokens: 3_050,
    calls_without_usage: 0,
  },
  by_agent: [
    { source: 'agent', agent: 'discoverer', models: ['qwen'], calls: 2, prompt_tokens: 4_000, completion_tokens: 150, total_tokens: 4_150, max_context_tokens: 3_050, calls_without_usage: 0 },
    { source: 'assistant', agent: 'chat', models: ['qwen'], calls: 4, prompt_tokens: 700, completion_tokens: 30, total_tokens: 730, max_context_tokens: 400, calls_without_usage: 0 },
  ],
  by_model: [
    { provider: 'ollama', model: 'qwen', calls: 6, prompt_tokens: 4_700, completion_tokens: 180, total_tokens: 4_880, max_context_tokens: 3_050, calls_without_usage: 0 },
  ],
  by_day: [{ day: '2026-10-14', calls: 6, prompt_tokens: 4_700, completion_tokens: 180 }],
}

const catalog = [
  { id: 'cheap/small', name: 'Small', context_length: 2_000, usd_per_million_in: 0.1, usd_per_million_out: 0.2, tools: true },
  { id: 'cheap/big', name: 'Big', context_length: 128_000, usd_per_million_in: 1, usd_per_million_out: 2, tools: true },
  { id: 'big/notools', name: 'NoTools', context_length: 128_000, usd_per_million_in: 0.05, usd_per_million_out: 0.05, tools: false },
]

function renderPanel() {
  render(
    <QueryClientProvider client={queryClient}>
      <CostPanel />
    </QueryClientProvider>,
  )
}

describe('CostPanel', () => {
  beforeEach(() => queryClient.clear())
  afterEach(() => vi.restoreAllMocks())

  it('shows the totals and the breakdown per agent, naming the chat assistant', async () => {
    server.use(http.get('/api/ai-mode/cost', () => HttpResponse.json(cost)))
    renderPanel()

    expect(await screen.findByText('4,880')).toBeInTheDocument()
    expect(screen.getByText('3,050', { selector: 'div' })).toBeInTheDocument()
    const row = screen.getByText('Chat assistant').closest('tr')!
    expect(within(row).getByText('15%')).toBeInTheDocument()
    expect(screen.getByText('discoverer')).toBeInTheDocument()
  })

  it('resets the counters after confirming', async () => {
    let resets = 0
    server.use(
      http.get('/api/ai-mode/cost', () => HttpResponse.json(cost)),
      http.post('/api/ai-mode/cost/reset', () => {
        resets += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Reset counters' }))
    await vi.waitFor(() => expect(resets).toBe(1))
  })

  it('ranks OpenRouter models by cost for the counted tokens, hiding ones that cannot fit or call tools', async () => {
    server.use(
      http.get('/api/ai-mode/cost', () => HttpResponse.json(cost)),
      http.get('/api/ai-mode/cost/openrouter-models', () => HttpResponse.json(catalog)),
    )
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Compare with OpenRouter models' }))
    expect(await screen.findByText('cheap/big')).toBeInTheDocument()
    expect(screen.queryByText('cheap/small')).not.toBeInTheDocument() // 2,000 < the 3,050 token call
    expect(screen.queryByText('big/notools')).not.toBeInTheDocument()
  })

  it('prices tokens per million', () => {
    expect(estimate(catalog[1], 1_000_000, 500_000)).toBeCloseTo(2)
  })
})
