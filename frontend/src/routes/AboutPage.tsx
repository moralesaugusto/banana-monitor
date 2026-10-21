import { useState } from 'react'
import { useResetAiMode } from '../api/aiMode'
import { useAbout, useResetInventory, useSetMaxDbSize } from '../api/about'
import { useOuiStatus, useUpdateOuiRegistry } from '../api/discovery'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'
import { SaveBar } from '../components/SaveBar'
import { CleanupCard } from './CleanupCard'

const rowClasses = 'flex items-center justify-between gap-4 border-b border-line px-4 py-2.5 last:border-b-0'

/** The IEEE OUI vendor registry used to label discovered devices by MAC
 * (docs/discovery.md) lives here rather than on the Discovery page itself -
 * it's a one-off system-level maintenance action, not part of reviewing
 * what a scan just found. */
function VendorDatabaseCard() {
  const { data: status } = useOuiStatus()
  const update = useUpdateOuiRegistry()

  const statusText =
    !status || status.entry_count === 0
      ? 'Not downloaded yet'
      : `${status.entry_count.toLocaleString()} vendors, updated ${new Date(status.updated_at!).toLocaleString()}`

  return (
    <Card className="p-4">
      <div className="text-sm font-medium text-fg">IEEE OUI vendor database</div>
      <p className="mt-1 text-xs text-fg-muted">
        Maps a discovered device's MAC address to a vendor name (e.g. "Raspberry Pi Foundation"). Never
        downloaded automatically — see <code className="font-mono">docs/discovery.md</code>.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-60"
          onClick={() => update.mutate()}
          disabled={update.isPending}
        >
          {update.isPending ? 'Updating…' : 'Update vendor database'}
        </button>
        <span className="text-xs text-fg-muted">{statusText}</span>
      </div>
      {update.isError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">Update failed — check connectivity.</p>
      )}
    </Card>
  )
}

function VersionCard() {
  const { data: about, isLoading, isError } = useAbout()

  return (
    <Card className="overflow-x-auto">
      <div className="px-4 py-2.5 text-sm font-medium text-fg">Version &amp; system</div>
      {isLoading && <div className="px-4 py-3 text-sm text-fg-muted">Loading…</div>}
      {isError && <div className="px-4 py-3 text-sm text-fg-muted">Could not load system info.</div>}
      {about && (
        <div>
          <div className={rowClasses}>
            <span className="text-fg-muted">Banana version</span>
            <span className="font-mono">{about.app_version}</span>
          </div>
          <div className={rowClasses}>
            <span className="text-fg-muted">Python</span>
            <span className="font-mono">{about.python_version}</span>
          </div>
          <div className={rowClasses}>
            <span className="text-fg-muted">Platform</span>
            <span className="font-mono text-right">{about.platform}</span>
          </div>
          <div className={rowClasses}>
            <span className="text-fg-muted">Hostname</span>
            <span className="font-mono">{about.hostname}</span>
          </div>
          <div className={rowClasses}>
            <span className="text-fg-muted">HTTPS</span>
            <span className="font-mono">{about.https_enabled ? 'enabled' : 'disabled'}</span>
          </div>
          <div className={rowClasses}>
            <span className="text-fg-muted">Data directory</span>
            <span className="font-mono">{about.data_dir}</span>
          </div>
        </div>
      )}
    </Card>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function StorageCard() {
  const { data: about } = useAbout()
  const setMax = useSetMaxDbSize()
  const [draft, setDraft] = useState<string | null>(null)
  if (!about?.storage) return null

  const limit = about.max_db_size_mb ?? 512
  const metrics = about.storage.find((f) => f.name === 'metrics.db')
  const usedPct = metrics ? Math.min(100, (metrics.size_bytes / (limit * 1024 * 1024)) * 100) : 0
  const value = draft ?? String(limit)

  return (
    <Card className="p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setMax.mutate(Number(value), { onSuccess: () => setDraft(null) })
        }}
      >
        <SaveBar
          title="Storage"
          saving={setMax.isPending}
          saved={setMax.isSuccess && draft === null}
          error={setMax.isError ? setMax.error.message : null}
        />
        <div className="mt-2 divide-y divide-line text-sm">
          {about.storage.map((file) => (
            <div key={file.name} className="flex justify-between py-1.5">
              <span className="font-mono text-fg-muted">{file.name}</span>
              <span className="font-mono">{formatBytes(file.size_bytes)}</span>
            </div>
          ))}
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-fg-subtle/20" title={`metrics.db is ${usedPct.toFixed(0)}% of its cap`}>
          <div className={`h-full ${usedPct > 90 ? 'bg-red-500' : 'bg-accent'}`} style={{ width: `${usedPct}%` }} />
        </div>
        <label className="mt-3 flex flex-col text-sm">
          Metrics database cap (MB)
          <input
            type="number"
            min={16}
            className="mt-1 w-32 rounded-control border border-line bg-surface px-2 py-1 text-sm"
            value={value}
            onChange={(e) => setDraft(e.target.value)}
          />
        </label>
        <p className="mt-2 text-xs text-fg-muted">
          When metrics.db passes the cap, the oldest check results, samples and rollups are deleted and the file is
          compacted. Checked every 5 minutes. app.db and credentials.db hold configuration and are never trimmed.
        </p>
      </form>
    </Card>
  )
}

function SecurityCard() {
  const { data: about } = useAbout()
  if (!about?.security?.length) return null
  const tone = (ok: boolean | null) =>
    ok === null ? 'text-fg-muted' : ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
  return (
    <Card className="overflow-x-auto">
      <div className="px-4 py-2.5 text-sm font-medium text-fg">Security posture</div>
      {about.security.map((check) => (
        <div key={check.label} className={rowClasses + ' items-start'}>
          <span className="text-fg-muted">{check.label}</span>
          <span className="text-right">
            <span className={`font-mono text-sm ${tone(check.ok)}`}>{check.value}</span>
            {check.detail && <span className="block text-xs text-fg-muted">{check.detail}</span>}
          </span>
        </div>
      ))}
      <p className="px-4 py-3 text-xs text-fg-muted">
        This installation stores SSH and API credentials. Back up the master key separately from the data
        directory; without it stored credentials cannot be decrypted. See docs/credentials.md.
      </p>
    </Card>
  )
}

function ResetCard() {
  const reset = useResetInventory()
  return (
    <Card className="border-red-500/40 p-4">
      <div className="text-sm font-medium text-fg">Start from scratch</div>
      <p className="mt-1 text-xs text-fg-muted">
        Deletes every device and service, discovery candidates, and their history. Networks, integrations,
        credentials, alert rules and settings are kept; run a scan afterwards to rediscover hosts.
      </p>
      <button
        type="button"
        disabled={reset.isPending}
        className="mt-3 rounded-control border border-red-500/60 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
        onClick={() => {
          if (window.prompt('Type RESET to delete all devices and services') === 'RESET') reset.mutate()
        }}
      >
        Delete all devices and services
      </button>
      {reset.isSuccess && (
        <p className="mt-2 text-xs text-fg-muted">
          Removed {reset.data.devices} device(s) and {reset.data.services} service(s).
        </p>
      )}
      {reset.isError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">Reset failed.</p>}
    </Card>
  )
}

function AiResetCard() {
  const reset = useResetAiMode()
  return (
    <Card className="border-red-500/40 p-4">
      <div className="text-sm font-medium text-fg">Start from scratch (AI subsystem)</div>
      <p className="mt-1 text-xs text-fg-muted">
        Deletes every AI run and message, all agents, custom tools, guardrails and the schedule, and puts every setting back to its
        default. AI Mode is switched off. Services the agents already recorded are kept. A run in progress must be stopped first.
      </p>
      <button
        type="button"
        disabled={reset.isPending}
        className="mt-3 rounded-control border border-red-600 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-600/10 disabled:opacity-50"
        onClick={() => {
          if (window.confirm('Delete all AI Mode runs, agents, tools and settings and start from scratch?')) reset.mutate()
        }}
      >
        Reset AI Mode
      </button>
      {reset.isSuccess && <p className="mt-2 text-sm text-fg-muted">AI Mode is back to its defaults.</p>}
      {reset.isError && <p className="mt-2 text-sm text-red-600">{String((reset.error as Error).message).slice(0, 200)}</p>}
    </Card>
  )
}

export function AboutPage() {
  return (
    <div>
      <PageHeader title="About" description="Version, runtime, and maintenance actions for this installation." />

      <div className="mt-6 flex flex-col gap-6">
        <VersionCard />
        <SecurityCard />
        <StorageCard />
        <VendorDatabaseCard />
        <CleanupCard />
        <ResetCard />
        <AiResetCard />
      </div>
    </div>
  )
}
