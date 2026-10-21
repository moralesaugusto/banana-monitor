import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  reportPdfUrl,
  useCreateSnapshotReport,
  useDeleteAllReports,
  useDeleteReport,
  useGenerateAiReport,
  useReport,
  useReports,
} from '../api/reports'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'
const ghostButtonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'

const SOURCE_LABELS: Record<string, string> = {
  snapshot: 'Snapshot',
  telegram: 'Telegram',
  agent: 'Reporter agent',
}

function ReportView({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { data: report } = useReport(id)
  const remove = useDeleteReport()
  if (!report) return <p className="text-sm text-fg-muted">Loading…</p>
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-fg">{report.title}</h2>
        <div className="flex gap-2">
          <a className={ghostButtonClasses} href={reportPdfUrl(report.id)} download>
            Download PDF
          </a>
          <button
            type="button"
            className="rounded-control border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete ${report.title}?`)) remove.mutate(report.id, { onSuccess: onDeleted })
            }}
          >
            Delete
          </button>
        </div>
      </div>
      <div className="report-body mt-4 overflow-x-auto text-sm text-fg">
        <Markdown remarkPlugins={[remarkGfm]}>{report.content}</Markdown>
      </div>
    </Card>
  )
}

export function ReportsPage() {
  const { data: reports, isLoading } = useReports()
  const snapshot = useCreateSnapshotReport()
  const generate = useGenerateAiReport()
  const deleteAll = useDeleteAllReports()
  const [selected, setSelected] = useState<number | null>(null)
  const current = selected ?? reports?.[0]?.id ?? null

  return (
    <div>
      <PageHeader
        title="Reports"
        description="Network and services reports. Download any of them as PDF, or ask the bot for one on Telegram."
      />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={primaryButtonClasses}
          disabled={snapshot.isPending}
          onClick={() => snapshot.mutate(undefined, { onSuccess: (r) => setSelected(r.id) })}
        >
          {snapshot.isPending ? 'Building…' : 'Create report now'}
        </button>
        <button
          type="button"
          className={ghostButtonClasses}
          disabled={generate.isPending}
          title="The reporter agent reads the network and writes the report. Needs AI Mode switched on."
          onClick={() => generate.mutate()}
        >
          Ask the reporter agent
        </button>
        {reports && reports.length > 0 && (
          <button
            type="button"
            className="rounded-control border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-950"
            disabled={deleteAll.isPending}
            onClick={() => {
              if (window.confirm(`Delete all ${reports.length} report(s)? This cannot be undone.`)) {
                deleteAll.mutate(undefined, { onSuccess: () => setSelected(null) })
              }
            }}
          >
            Delete all
          </button>
        )}
        {generate.isSuccess && (
          <span className="text-sm text-fg-muted">Reporter started (run {generate.data.run_id}). The report appears here when it is saved.</span>
        )}
        {(snapshot.error ?? generate.error ?? deleteAll.error) && (
          <span className="text-sm text-red-600 dark:text-red-400">
            {(snapshot.error ?? generate.error ?? deleteAll.error)?.message}
          </span>
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card className="self-start overflow-hidden">
          {isLoading && <p className="p-4 text-sm text-fg-muted">Loading…</p>}
          {reports?.length === 0 && <p className="p-4 text-sm text-fg-muted">No reports yet.</p>}
          <ul>
            {reports?.map((report) => (
              <li key={report.id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  className={`w-full px-4 py-2.5 text-left hover:bg-accent-soft/60 ${report.id === current ? 'bg-accent-soft' : ''}`}
                  onClick={() => setSelected(report.id)}
                >
                  <div className="text-sm font-medium text-fg">{report.title}</div>
                  <div className="text-xs text-fg-muted">
                    {SOURCE_LABELS[report.source] ?? report.source} · {new Date(report.created_at).toLocaleString()}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {current !== null && <ReportView key={current} id={current} onDeleted={() => setSelected(null)} />}
      </div>
    </div>
  )
}
