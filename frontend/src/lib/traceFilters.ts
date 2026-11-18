import type { AiRunStep } from '../api/aiMode'

export type StepFacet = 'agent' | 'tool'

export interface TraceFilters {
  agent: string[]
  tool: string[]
  errorsOnly: boolean
}

export const EMPTY_TRACE_FILTERS: TraceFilters = { agent: [], tool: [], errorsOnly: false }

export function stepFailed(step: AiRunStep): boolean {
  if (step.kind === 'error') return true
  const response = step.response
  return !!(response && typeof response === 'object' && 'error' in (response as Record<string, unknown>))
}

/** `skip` leaves one facet's own filter out, for counting that facet against the others. */
export function matchesTraceFilters(step: AiRunStep, filters: TraceFilters, skip?: StepFacet): boolean {
  if (filters.errorsOnly && !stepFailed(step)) return false
  if (skip !== 'agent' && filters.agent.length > 0 && !(step.agent && filters.agent.includes(step.agent))) {
    return false
  }
  if (skip !== 'tool' && filters.tool.length > 0) {
    if (step.kind !== 'tool' || !step.name || !filters.tool.includes(step.name)) return false
  }
  return true
}

export function filterSteps(steps: AiRunStep[], filters: TraceFilters): AiRunStep[] {
  return steps.filter((s) => matchesTraceFilters(s, filters))
}

/** Per-value counts for a facet, given every other active filter (never this facet's own), so a choice
 * never leads to an empty list. Selected values stay listed even at zero so they can be unticked. */
export function traceFacetCounts(steps: AiRunStep[], filters: TraceFilters, facet: StepFacet): [string, number][] {
  const counts = new Map<string, number>(filters[facet].map((v) => [v, 0]))
  for (const step of steps) {
    if (!matchesTraceFilters(step, filters, facet)) continue
    const value = facet === 'agent' ? step.agent : step.kind === 'tool' ? step.name : null
    if (value) counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

export function traceErrorCount(steps: AiRunStep[], filters: TraceFilters): number {
  const base = { ...filters, errorsOnly: false }
  return steps.filter((s) => matchesTraceFilters(s, base) && stepFailed(s)).length
}

export function hasActiveTraceFilters(filters: TraceFilters): boolean {
  return filters.errorsOnly || filters.agent.length + filters.tool.length > 0
}

export function traceFiltersFromParams(params: URLSearchParams): TraceFilters {
  return {
    agent: params.getAll('agent'),
    tool: params.getAll('tool'),
    errorsOnly: params.get('errors') === '1',
  }
}

export function traceFiltersToParams(filters: TraceFilters): URLSearchParams {
  const params = new URLSearchParams()
  filters.agent.forEach((v) => params.append('agent', v))
  filters.tool.forEach((v) => params.append('tool', v))
  if (filters.errorsOnly) params.set('errors', '1')
  return params
}
