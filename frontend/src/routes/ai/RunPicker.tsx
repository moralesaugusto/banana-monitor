import { useState } from 'react'
import { type AiRunSummary, useRunControl } from '../../api/aiMode'
import {
  EMPTY_FILTERS,
  filterRuns,
  hasActiveFilters,
  statusCounts,
  type Facet,
  type RunFilters,
  type StatusTab,
} from '../../lib/runFilters'
import { RunFilterPanel } from './RunFilterPanel'

const STATUS_TABS: [StatusTab, string][] = [
  ['all', 'All'],
  ['error', 'Errors'],
  ['running', 'Running'],
  ['scheduled', 'Scheduled'],
]

const buttonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'

export function RunPicker({
  runs,
  run,
  onChange,
}: {
  runs: AiRunSummary[]
  run: AiRunSummary | undefined
  onChange: (id: number) => void
}) {
  const control = useRunControl()
  const live = run?.status === 'running'
  const [open, setOpen] = useState(false)
  const [filters, setFilters] = useState<RunFilters>(EMPTY_FILTERS)

  const toggle = (facet: Facet, value: string) =>
    setFilters((f) => ({
      ...f,
      [facet]: f[facet].includes(value) ? f[facet].filter((v) => v !== value) : [...f[facet], value],
    }))
  const tabCounts = statusCounts(runs, filters)
  // Filtering only narrows what else can be picked; it never hides the run already selected.
  const visible = filterRuns(runs, filters)
  const options = runs.filter((r) => visible.includes(r) || r.id === run?.id)
  const active = hasActiveFilters(filters)

  return (
    <div className="flex flex-wrap items-start gap-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          Run
          <select
            className="rounded-control border border-line bg-surface px-2 py-1"
            value={run?.id ?? ''}
            onChange={(e) => onChange(Number(e.target.value))}
          >
            {options.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} {r.status} {new Date(r.started_at).toLocaleString()}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className={`${buttonClasses} ${active ? 'border-accent-strong text-accent-strong' : ''}`}
        >
          Filter{active ? ` (${filters.model.length + filters.agent.length + filters.tool.length + (filters.status !== 'all' ? 1 : 0)})` : ''}
        </button>
        {live && (
          <>
            <span className="flex items-center gap-1.5 text-fg-muted">
              <span className={`h-2 w-2 rounded-full ${run.paused ? 'bg-amber-500' : 'animate-pulse bg-emerald-500'}`} />
              {run.paused ? 'paused' : 'live'}
            </span>
            {run.paused ? (
              <button type="button" className={buttonClasses} onClick={() => control.resume.mutate(run.id)}>Resume</button>
            ) : (
              <button type="button" className={buttonClasses} onClick={() => control.pause.mutate(run.id)}>Pause</button>
            )}
            <button type="button" className={buttonClasses} onClick={() => control.stop.mutate(run.id)}>Stop run</button>
          </>
        )}
      </div>
      {open && (
        <div className="flex w-full flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {STATUS_TABS.map(([tab, label]) => (
              <button
                key={tab}
                type="button"
                aria-pressed={filters.status === tab}
                onClick={() => setFilters({ ...filters, status: tab })}
                className={`rounded-control border px-2.5 py-1 text-xs ${
                  filters.status === tab
                    ? 'border-accent-strong font-medium text-accent-strong'
                    : 'border-line text-fg-muted hover:text-fg'
                }`}
              >
                {label} <span className="tabular-nums text-fg-subtle">{tabCounts[tab]}</span>
              </button>
            ))}
            {active && (
              <button type="button" className="text-xs text-accent-strong hover:underline" onClick={() => setFilters(EMPTY_FILTERS)}>
                Clear all
              </button>
            )}
          </div>
          <RunFilterPanel
            runs={runs}
            filters={filters}
            onToggle={toggle}
            onClear={(facet) => setFilters({ ...filters, [facet]: [] })}
          />
        </div>
      )}
    </div>
  )
}
