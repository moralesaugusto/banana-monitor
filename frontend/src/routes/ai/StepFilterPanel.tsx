import { useState } from 'react'
import type { AiRunStep } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { traceErrorCount, traceFacetCounts, type StepFacet, type TraceFilters } from '../../lib/traceFilters'

const TITLES: Record<StepFacet, string> = { agent: 'Agents', tool: 'Tools' }
const SEARCH_THRESHOLD = 8

function FacetSection({
  facet, steps, filters, onToggle, onClear,
}: {
  facet: StepFacet
  steps: AiRunStep[]
  filters: TraceFilters
  onToggle: (facet: StepFacet, value: string) => void
  onClear: (facet: StepFacet) => void
}) {
  const [search, setSearch] = useState('')
  const counts = traceFacetCounts(steps, filters, facet)
  const shown = counts.filter(([value]) => value.toLowerCase().includes(search.toLowerCase()))
  return (
    <section aria-label={TITLES[facet]} className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{TITLES[facet]}</h3>
        {filters[facet].length > 0 && (
          <button type="button" className="text-xs text-accent-strong hover:underline" onClick={() => onClear(facet)}>
            Clear
          </button>
        )}
      </div>
      {counts.length > SEARCH_THRESHOLD && (
        <input
          type="search"
          aria-label={`Search ${TITLES[facet].toLowerCase()}`}
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mt-2 w-full rounded border border-line bg-surface px-2 py-1 text-xs"
        />
      )}
      <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
        {shown.length === 0 && <li className="text-xs text-fg-subtle">None in this run</li>}
        {shown.map(([value, count]) => (
          <li key={value}>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" checked={filters[facet].includes(value)} onChange={() => onToggle(facet, value)} />
              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={value}>{value}</span>
              <span className="text-xs tabular-nums text-fg-muted">{count}</span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Note: a model filter is deliberately not offered here - a run uses one model throughout (shown
 * above in Run metrics); only Agents and Tools vary step to step. */
export function StepFilterPanel(props: {
  steps: AiRunStep[]
  filters: TraceFilters
  onToggle: (facet: StepFacet, value: string) => void
  onClear: (facet: StepFacet) => void
  onToggleErrorsOnly: () => void
}) {
  const errorCount = traceErrorCount(props.steps, props.filters)
  return (
    <aside aria-label="Filters" className="w-full shrink-0 lg:sticky lg:top-4 lg:w-64 lg:self-start">
      <Card>
        <section className="border-b border-line px-4 py-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={props.filters.errorsOnly} onChange={props.onToggleErrorsOnly} />
            <span className="flex-1">Errors only</span>
            <span className="text-xs tabular-nums text-fg-muted">{errorCount}</span>
          </label>
        </section>
        {(['agent', 'tool'] as const).map((facet) => (
          <FacetSection key={facet} facet={facet} {...props} />
        ))}
      </Card>
    </aside>
  )
}
