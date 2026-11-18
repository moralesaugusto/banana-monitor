import type { AiRunSummary } from '../api/aiMode'

export type Facet = 'model' | 'agent' | 'tool'
export type StatusTab = 'all' | 'error' | 'running' | 'scheduled'

export interface RunFilters {
  model: string[]
  agent: string[]
  tool: string[]
  status: StatusTab
}

export const EMPTY_FILTERS: RunFilters = { model: [], agent: [], tool: [], status: 'all' }

const FACET_VALUES: Record<Facet, (run: AiRunSummary) => string[]> = {
  model: (run) => (run.model ? [run.model] : []),
  agent: (run) => run.agents ?? [],
  tool: (run) => run.tools ?? [],
}

function matchesStatus(run: AiRunSummary, status: StatusTab): boolean {
  if (status === 'error') return run.status === 'error'
  if (status === 'running') return run.status === 'running'
  if (status === 'scheduled') return run.started_by === 'schedule'
  return true
}

/** Values within a facet are OR'd, facets (and the status tab) are AND'd. `skip` leaves one facet out. */
export function matchesFilters(run: AiRunSummary, filters: RunFilters, skip?: Facet): boolean {
  if (!matchesStatus(run, filters.status)) return false
  return (['model', 'agent', 'tool'] as const).every((facet) => {
    if (facet === skip || filters[facet].length === 0) return true
    const values = FACET_VALUES[facet](run)
    return filters[facet].some((v) => values.includes(v))
  })
}

export function filterRuns(runs: AiRunSummary[], filters: RunFilters): AiRunSummary[] {
  return runs.filter((run) => matchesFilters(run, filters))
}

/** Per-value counts for a facet, given every other active filter, so a choice never leads to an empty list.
 * Selected values stay listed even at zero so they can be unticked. */
export function facetCounts(runs: AiRunSummary[], filters: RunFilters, facet: Facet): [string, number][] {
  const counts = new Map<string, number>(filters[facet].map((v) => [v, 0]))
  for (const run of runs) {
    if (!matchesFilters(run, filters, facet)) continue
    for (const value of FACET_VALUES[facet](run)) counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

export function statusCounts(runs: AiRunSummary[], filters: RunFilters): Record<StatusTab, number> {
  const base = { ...filters, status: 'all' as const }
  const visible = runs.filter((run) => matchesFilters(run, base))
  return {
    all: visible.length,
    error: visible.filter((r) => matchesStatus(r, 'error')).length,
    running: visible.filter((r) => matchesStatus(r, 'running')).length,
    scheduled: visible.filter((r) => matchesStatus(r, 'scheduled')).length,
  }
}

export function filtersFromParams(params: URLSearchParams): RunFilters {
  const status = params.get('status')
  return {
    model: params.getAll('model'),
    agent: params.getAll('agent'),
    tool: params.getAll('tool'),
    status: status === 'error' || status === 'running' || status === 'scheduled' ? status : 'all',
  }
}

export function filtersToParams(filters: RunFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const facet of ['model', 'agent', 'tool'] as const) filters[facet].forEach((v) => params.append(facet, v))
  if (filters.status !== 'all') params.set('status', filters.status)
  return params
}

export function hasActiveFilters(filters: RunFilters): boolean {
  return filters.status !== 'all' || filters.model.length + filters.agent.length + filters.tool.length > 0
}
