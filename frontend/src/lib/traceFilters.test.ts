import { describe, expect, it } from 'vitest'
import type { AiRunStep } from '../api/aiMode'
import {
  EMPTY_TRACE_FILTERS,
  filterSteps,
  hasActiveTraceFilters,
  traceErrorCount,
  traceFacetCounts,
  traceFiltersFromParams,
  traceFiltersToParams,
} from './traceFilters'

function step(idx: number, over: Partial<AiRunStep>): AiRunStep {
  return {
    idx,
    ts: '2026-11-14T10:00:00Z',
    kind: 'tool',
    name: null,
    agent: null,
    request: {},
    response: {},
    duration_ms: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    ...over,
  }
}

const STEPS = [
  step(0, { kind: 'llm', agent: 'discoverer', response: { tool_calls: [] } }),
  step(1, { kind: 'tool', name: 'run_nmap', agent: 'discoverer', response: { exit_code: 0 } }),
  step(2, { kind: 'tool', name: 'run_nc', agent: 'reviewer', response: { error: 'timed out' } }),
  step(3, { kind: 'error', agent: 'reviewer', response: { error: 'boom' } }),
]

describe('traceFilters', () => {
  it('ORs values within a facet and ANDs across facets, and errorsOnly keeps only failed steps', () => {
    const idx = (f: Partial<typeof EMPTY_TRACE_FILTERS>) =>
      filterSteps(STEPS, { ...EMPTY_TRACE_FILTERS, ...f }).map((s) => s.idx)
    expect(idx({ agent: ['discoverer'] })).toEqual([0, 1])
    expect(idx({ agent: ['discoverer'], tool: ['run_nmap'] })).toEqual([1])
    expect(idx({ tool: ['run_nc'] })).toEqual([2]) // llm/error steps never match a tool filter
    expect(idx({ errorsOnly: true })).toEqual([2, 3])
  })

  it('counts a facet against the other filters only, keeping selected zero-count values', () => {
    const filters = { ...EMPTY_TRACE_FILTERS, agent: ['reviewer'], tool: ['run_nmap'] }
    // counting 'agent' ignores the agent filter but keeps the tool filter: only discoverer's run_nmap
    // step (idx 1) matches tool:run_nmap, so discoverer picks up a count even though it isn't selected.
    expect(traceFacetCounts(STEPS, filters, 'agent')).toEqual([
      ['discoverer', 1],
      ['reviewer', 0],
    ])
    expect(traceFacetCounts(STEPS, filters, 'tool')).toEqual([
      ['run_nc', 1],
      ['run_nmap', 0],
    ])
  })

  it('counts errors ignoring errorsOnly itself but respecting other filters', () => {
    expect(traceErrorCount(STEPS, EMPTY_TRACE_FILTERS)).toBe(2)
    expect(traceErrorCount(STEPS, { ...EMPTY_TRACE_FILTERS, agent: ['discoverer'] })).toBe(0)
  })

  it('round-trips through URL params', () => {
    const filters = { agent: ['x', 'y'], tool: ['run_nc'], errorsOnly: true }
    expect(traceFiltersFromParams(traceFiltersToParams(filters))).toEqual(filters)
    expect(hasActiveTraceFilters(filters)).toBe(true)
    expect(hasActiveTraceFilters(EMPTY_TRACE_FILTERS)).toBe(false)
  })
})
