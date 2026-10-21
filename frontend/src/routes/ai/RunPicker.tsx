import { type AiRunSummary, useRunControl } from '../../api/aiMode'

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
  const buttonClasses =
    'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50'
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <label className="flex items-center gap-2">
        Run
        <select
          className="rounded-control border border-line bg-surface px-2 py-1"
          value={run?.id ?? ''}
          onChange={(e) => onChange(Number(e.target.value))}
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              #{r.id} {r.status} {new Date(r.started_at).toLocaleString()}
            </option>
          ))}
        </select>
      </label>
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
  )
}
