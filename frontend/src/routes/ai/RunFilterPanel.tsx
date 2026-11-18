import { useState } from 'react'
import type { AiRunSummary } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { facetCounts, type Facet, type RunFilters } from '../../lib/runFilters'

const TITLES: Record<Facet, string> = { model: 'Models', agent: 'Agents', tool: 'Tools' }
const SEARCH_THRESHOLD = 8

function FacetSection({
  facet, runs, filters, onToggle, onClear,
}: {
  facet: Facet
  runs: AiRunSummary[]
  filters: RunFilters
  onToggle: (facet: Facet, value: string) => void
  onClear: (facet: Facet) => void
}) {
  const [search, setSearch] = useState('')
  const counts = facetCounts(runs, filters, facet)
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
        {shown.length === 0 && <li className="text-xs text-fg-subtle">None in these runs</li>}
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

export function RunFilterPanel(props: {
  runs: AiRunSummary[]
  filters: RunFilters
  onToggle: (facet: Facet, value: string) => void
  onClear: (facet: Facet) => void
}) {
  return (
    <aside aria-label="Filters" className="w-full shrink-0 lg:sticky lg:top-4 lg:w-64 lg:self-start">
      <Card>
        {(['model', 'agent', 'tool'] as const).map((facet) => (
          <FacetSection key={facet} facet={facet} {...props} />
        ))}
      </Card>
    </aside>
  )
}
