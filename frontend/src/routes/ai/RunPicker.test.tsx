import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AiRunSummary } from '../../api/aiMode'
import { queryClient } from '../../lib/queryClient'
import { RunPicker } from './RunPicker'

function run(id: number, over: Partial<AiRunSummary>): AiRunSummary {
  return {
    id,
    started_at: '2026-11-14T10:00:00Z',
    finished_at: null,
    status: 'done',
    targets: [],
    dry_run: false,
    model: 'a',
    prompt_tokens: 0,
    completion_tokens: 0,
    summary: null,
    error: null,
    step_count: 0,
    services_recorded: 0,
    agents: [],
    tools: [],
    ...over,
  }
}

const RUNS = [
  run(3, { model: 'a', agents: ['x'], tools: ['nmap'], status: 'error' }),
  run(2, { model: 'b', agents: ['y'], tools: ['nc'] }),
  run(1, { model: 'a', agents: ['y'], tools: [] }),
]

function renderPicker(selected: AiRunSummary, onChange = vi.fn()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <RunPicker runs={RUNS} run={selected} onChange={onChange} />
    </QueryClientProvider>,
  )
}

function options(): string[] {
  return [...screen.getByRole('combobox').querySelectorAll('option')].map((o) => o.textContent ?? '')
}

describe('RunPicker filters', () => {
  it('narrows the dropdown using the same model/agent/tool/status filters as run history', async () => {
    renderPicker(RUNS[0]) // run #3, model a - stays in the options once filtered to model a
    expect(options()).toHaveLength(3)

    await userEvent.click(screen.getByRole('button', { name: /^Filter/ }))
    await userEvent.click(screen.getByLabelText(/^a/))

    expect(options().map((o) => o.split(' ')[0])).toEqual(['#3', '#1'])
    expect(screen.getByRole('button', { name: /^Filter \(1\)/ })).toBeInTheDocument()
  })

  it('never hides the currently selected run, even once filtered out', async () => {
    renderPicker(RUNS[1]) // run #2, model b

    await userEvent.click(screen.getByRole('button', { name: /^Filter/ }))
    await userEvent.click(screen.getByLabelText(/^a/))

    const shown = options().map((o) => o.split(' ')[0])
    expect(shown).toContain('#2')
    expect(shown).toEqual(['#3', '#2', '#1'])
  })

  it('filters by status and clears all filters', async () => {
    renderPicker(RUNS[0])
    await userEvent.click(screen.getByRole('button', { name: /^Filter/ }))

    await userEvent.click(screen.getByRole('button', { name: /^Errors/ }))
    expect(options().map((o) => o.split(' ')[0])).toEqual(['#3'])

    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(options()).toHaveLength(3)
  })
})
