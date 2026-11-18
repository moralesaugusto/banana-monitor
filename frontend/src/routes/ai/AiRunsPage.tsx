import { Link, useSearchParams } from 'react-router-dom'
import { useAiRuns } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { formatDuration } from '../../lib/format'
import {
  EMPTY_FILTERS,
  filterRuns,
  filtersFromParams,
  filtersToParams,
  hasActiveFilters,
  statusCounts,
  type Facet,
  type RunFilters,
  type StatusTab,
} from '../../lib/runFilters'
import { RunFilterPanel } from './RunFilterPanel'

function duration(startedAt: string, finishedAt: string | null): string {
  if (finishedAt == null) return 'running'
  return formatDuration(new Date(finishedAt).getTime() - new Date(startedAt).getTime())
}

const TABS: [StatusTab, string][] = [['all', 'All'], ['error', 'Errors'], ['running', 'Running'], ['scheduled', 'Scheduled']]

/** A cell that applies its value as a filter on click. */
function FilterCell({ children, onClick, title }: { children: string; onClick: () => void; title: string }) {
  return (
    <button type="button" title={title} onClick={onClick} className="font-mono text-xs hover:text-accent-strong hover:underline">
      {children}
    </button>
  )
}

export function AiRunsPage() {
  const { data: allRuns, isLoading } = useAiRuns()
  const [params, setParams] = useSearchParams()
  const filters = filtersFromParams(params)
  const update = (next: RunFilters) => setParams(filtersToParams(next), { replace: true })
  const toggle = (facet: Facet, value: string) =>
    update({
      ...filters,
      [facet]: filters[facet].includes(value) ? filters[facet].filter((v) => v !== value) : [...filters[facet], value],
    })
  const select = (facet: Facet, value: string) => {
    if (!filters[facet].includes(value)) toggle(facet, value)
  }
  const runs = allRuns && filterRuns(allRuns, filters)
  const tabCounts = statusCounts(allRuns ?? [], filters)
  const chips = (['model', 'agent', 'tool'] as const).flatMap((facet) => filters[facet].map((value) => ({ facet, value })))
  return (
    <div>
      <PageHeader title="Run history" description="Every AI Mode run is kept with its full trace so you can review and learn from it. Open a run for the full step-by-step trace; a failed or odd-looking run's reason is shown here too, so you don't have to open every one to triage." />
      <div className="mt-6 flex flex-wrap gap-1 border-b border-line">
        {TABS.map(([tab, label]) => (
          <button
            key={tab}
            type="button"
            aria-pressed={filters.status === tab}
            onClick={() => update({ ...filters, status: tab })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${filters.status === tab ? 'border-accent-strong font-medium text-fg' : 'border-transparent text-fg-muted hover:text-fg'}`}
          >
            {label} <span className="tabular-nums text-fg-subtle">{tabCounts[tab]}</span>
          </button>
        ))}
      </div>
      {hasActiveFilters(filters) && (
        <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Active filters">
          {chips.map(({ facet, value }) => (
            <button
              key={`${facet}:${value}`}
              type="button"
              aria-label={`Remove ${facet} filter ${value}`}
              onClick={() => toggle(facet, value)}
              className="rounded-full border border-line bg-surface px-2.5 py-0.5 font-mono text-xs hover:bg-line/40"
            >
              {facet}: {value} &times;
            </button>
          ))}
          <button type="button" className="text-xs text-accent-strong hover:underline" onClick={() => update(EMPTY_FILTERS)}>
            Clear all
          </button>
        </div>
      )}
      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
        <Card className="min-w-0 flex-1 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Run</th>
                <th className="px-4 py-2.5 font-medium">Started</th>
                <th className="px-4 py-2.5 font-medium">Duration</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Entry agent</th>
                <th className="px-4 py-2.5 font-medium">Model</th>
                <th className="px-4 py-2.5 font-medium">Targets</th>
                <th className="px-4 py-2.5 font-medium">Steps</th>
                <th className="px-4 py-2.5 font-medium">Recorded</th>
                <th className="px-4 py-2.5 font-medium">Tokens</th>
                <th className="px-4 py-2.5 font-medium">Error / summary</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={11} className="px-4 py-3 text-fg-muted">Loading...</td>
                </tr>
              )}
              {runs?.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-3 text-fg-muted">
                    {allRuns?.length ? 'No runs match these filters.' : 'No runs yet.'}
                  </td>
                </tr>
              )}
              {runs?.map((run) => (
                <tr key={run.id} className="border-b border-line last:border-b-0">
                  <td className="px-4 py-2.5">
                    <Link className="font-medium text-accent-strong hover:underline" to={`/ai/runs/${run.id}`}>
                      #{run.id}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{new Date(run.started_at).toLocaleString()}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{duration(run.started_at, run.finished_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <span className={run.status === 'error' ? 'font-medium text-red-600' : undefined}>
                      {run.status}
                    </span>
                    {run.dry_run ? ' (dry)' : ''}
                    {run.stop_reason === 'time_limit' && <span className="ml-1 text-xs text-amber-600">stopped at time limit</span>}
                    {run.stop_reason === 'manual' && <span className="ml-1 text-xs text-fg-muted">stopped by hand</span>}
                    {run.started_by === 'schedule' && <span className="ml-1 text-xs text-fg-subtle">scheduled</span>}
                  </td>
                  <td className="px-4 py-2.5 text-fg-muted">
                    {run.entry_agent ? (
                      <FilterCell title={`Filter by agent ${run.entry_agent}`} onClick={() => select('agent', run.entry_agent!)}>
                        {run.entry_agent}
                      </FilterCell>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <FilterCell title={`Filter by model ${run.model}`} onClick={() => select('model', run.model)}>
                      {run.model}
                    </FilterCell>
                  </td>
                  <td className="max-w-56 truncate px-4 py-2.5 font-mono text-xs text-fg-muted" title={run.targets.join(', ')}>
                    {run.targets.join(', ')}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{run.step_count}</td>
                  <td className="px-4 py-2.5 tabular-nums">{run.services_recorded}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs tabular-nums text-fg-muted">
                    {run.prompt_tokens} / {run.completion_tokens}
                  </td>
                  <td className="max-w-72 truncate px-4 py-2.5 text-xs" title={run.error ?? run.summary ?? undefined}>
                    {run.error ? (
                      <span className="text-red-600">{run.error}</span>
                    ) : run.summary ? (
                      <span className="text-fg-muted">{run.summary}</span>
                    ) : (
                      <span className="text-fg-subtle">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <RunFilterPanel runs={allRuns ?? []} filters={filters} onToggle={toggle} onClear={(facet) => update({ ...filters, [facet]: [] })} />
      </div>
    </div>
  )
}
