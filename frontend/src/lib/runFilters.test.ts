import { describe, expect, it } from 'vitest'
import type { AiRunSummary } from '../api/aiMode'
import {
  EMPTY_FILTERS,
  facetCounts,
  filterRuns,
  filtersFromParams,
  filtersToParams,
  statusCounts,
} from './runFilters'

function run(id: number, over: Partial<AiRunSummary>): AiRunSummary {
  return {
    id, started_at: '2026-10-13T20:48:17Z', finished_at: null, status: 'done', targets: [], dry_run: false,
    model: 'a', prompt_tokens: 0, completion_tokens: 0, summary: null, error: null, step_count: 0,
    services_recorded: 0, agents: [], tools: [], ...over,
  }
}

const RUNS = [
  run(1, { model: 'a', agents: ['x'], tools: ['nmap'], status: 'error' }),
  run(2, { model: 'a', agents: ['x', 'y'], tools: ['nmap', 'nc'], started_by: 'schedule' }),
  run(3, { model: 'b', agents: ['y'], tools: ['nc'] }),
]

describe('runFilters', () => {
  it('ORs values within a facet and ANDs across facets', () => {
    const ids = (f: Partial<typeof EMPTY_FILTERS>) => filterRuns(RUNS, { ...EMPTY_FILTERS, ...f }).map((r) => r.id)
    expect(ids({ model: ['a', 'b'] })).toEqual([1, 2, 3])
    expect(ids({ model: ['a'], tool: ['nc'] })).toEqual([2])
    expect(ids({ agent: ['y'], status: 'scheduled' })).toEqual([2])
    expect(ids({ status: 'error' })).toEqual([1])
  })

  it('counts a facet against the other filters only, keeping selected zero-count values', () => {
    const filters = { ...EMPTY_FILTERS, model: ['b'], tool: ['nmap'] }
    expect(facetCounts(RUNS, filters, 'model')).toEqual([['a', 2], ['b', 0]])
    expect(facetCounts(RUNS, filters, 'tool')).toEqual([['nc', 1], ['nmap', 0]])
  })

  it('counts status tabs against the facet filters', () => {
    expect(statusCounts(RUNS, { ...EMPTY_FILTERS, model: ['a'] })).toEqual({ all: 2, error: 1, running: 0, scheduled: 1 })
  })

  it('round-trips through URL params, ignoring an unknown status', () => {
    const filters = { model: ['a'], agent: ['x', 'y'], tool: [], status: 'error' as const }
    expect(filtersFromParams(filtersToParams(filters))).toEqual(filters)
    expect(filtersFromParams(new URLSearchParams('status=bogus')).status).toBe('all')
  })
})
