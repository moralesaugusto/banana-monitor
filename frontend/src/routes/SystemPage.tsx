import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  type DiscoverySettings,
  useDiscoverySettings,
  useScanAll,
  useInternetAccess,
  useScanOverview,
  useSetInternetBlocked,
  useUpdateDiscoverySettings,
} from '../api/system'
import { type TelegramUpdate, useTelegramConfig, useTelegramTest, useUpdateTelegramConfig } from '../api/telegram'
import { Card } from '../components/Card'
import { ChangePasswordForm } from '../components/ChangePasswordForm'
import { PageHeader } from '../components/PageHeader'
import { SaveBar } from '../components/SaveBar'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex flex-col text-sm">
      {label}
      <input
        type="number"
        className={`${inputClasses} w-28`}
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function ScanCard({ settings }: { settings: DiscoverySettings }) {
  const update = useUpdateDiscoverySettings()
  const scanAll = useScanAll()
  const { data: overview } = useScanOverview()
  const [draft, setDraft] = useState(settings)
  const set = <K extends keyof DiscoverySettings>(key: K, value: DiscoverySettings[K]) => {
    update.reset()
    setDraft({ ...draft, [key]: value })
  }

  return (
    <Card className="p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate(draft)
        }}
      >
        <SaveBar
          title="Network scanning and fingerprinting"
          description="Open ports found by a scan are listed in Services, then identified with nmap. Scans run in the background; the UI stays usable."
          saving={update.isPending}
          saved={update.isSuccess}
          error={update.isError ? 'Failed to save settings.' : null}
        />

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="flex flex-col text-sm">
            Scan mode
            <select
              className={inputClasses}
              value={draft.scan_mode}
              onChange={(e) => set('scan_mode', e.target.value as 'manual' | 'auto')}
            >
              <option value="auto">Automatic</option>
              <option value="manual">Manual only</option>
            </select>
          </label>
          {draft.scan_mode === 'auto' && (
            <NumberField
              label="Interval (seconds)"
              value={draft.auto_interval_seconds}
              min={60}
              max={86400}
              onChange={(v) => set('auto_interval_seconds', v)}
            />
          )}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.nmap_enabled}
              onChange={(e) => set('nmap_enabled', e.target.checked)}
            />
            Fingerprint services with nmap
          </label>
          <label className="flex items-center gap-2 text-sm" title="Auto-login tries the credentials bound to a network on SSH hosts it finds. With this on, it waits until you approve each host's SSH key (Discovery page).">
            <input
              type="checkbox"
              checked={draft.ssh_hostkey_approval}
              onChange={(e) => set('ssh_hostkey_approval', e.target.checked)}
            />
            Approve SSH host keys before auto-login sends a password
          </label>
          <label className="flex items-center gap-2 text-sm" title="A known host presenting a different SSH key is re-pinned automatically instead of pausing for re-approval - useful on a LAN where an IP gets reassigned to a new machine. Turn off for strict pinning.">
            <input
              type="checkbox"
              checked={draft.ssh_hostkey_auto_repin}
              onChange={(e) => set('ssh_hostkey_auto_repin', e.target.checked)}
            />
            Re-pin a changed SSH host key automatically
          </label>
        </div>

        <div className="mt-4">
          <label className="flex max-w-sm flex-col text-sm">
            DNS server for host names
            <input
              className={`${inputClasses} font-mono`}
              placeholder="empty = this machine's resolver, e.g. 192.168.1.3"
              value={draft.dns_server}
              onChange={(e) => set('dns_server', e.target.value.trim())}
            />
            <span className="mt-1 text-xs text-fg-muted">
              Scans ask it for each device's name (your router or AdGuard Home usually knows its DHCP clients). Devices
              are also asked for their own name over mDNS and NetBIOS, and Linux hosts report theirs over SSH.
            </span>
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="flex flex-col text-sm">
            Timing template
            <select
              className={inputClasses}
              value={draft.timing_template}
              onChange={(e) => set('timing_template', Number(e.target.value))}
            >
              <option value={3}>T3 normal</option>
              <option value={4}>T4 aggressive</option>
              <option value={5}>T5 insane</option>
            </select>
          </label>
          <NumberField label="Host timeout (s)" value={draft.host_timeout_seconds} min={5} max={300}
            onChange={(v) => set('host_timeout_seconds', v)} />
          <NumberField label="Max retries" value={draft.max_retries} min={0} max={5}
            onChange={(v) => set('max_retries', v)} />
          <NumberField label="Version intensity" value={draft.version_intensity} min={0} max={9}
            onChange={(v) => set('version_intensity', v)} />
        </div>
      </form>

      <div className="mt-4 flex items-center gap-3 border-t border-line pt-4">
        <button
          type="button"
          className={primaryButtonClasses}
          onClick={() => scanAll.mutate()}
          disabled={scanAll.isPending || overview?.scanning}
        >
          {overview?.scanning ? 'Scanning...' : 'Scan all networks now'}
        </button>
        {overview?.scanning && (
          <span className="text-xs text-fg-muted">
            {overview.scanned_hosts}/{overview.total_hosts} hosts
          </span>
        )}
        <span className="text-xs text-fg-muted">Scanning uses the saved settings.</span>
      </div>
    </Card>
  )
}

function InternetKillSwitchCard() {
  const { data } = useInternetAccess()
  const setBlocked = useSetInternetBlocked()
  const { hash } = useLocation()
  const loaded = Boolean(data)
  useEffect(() => {
    if (loaded && hash === '#internet') document.getElementById('internet')?.scrollIntoView?.()
  }, [loaded, hash])
  if (!data) return null
  return (
    <Card id="internet" className="p-4">
      <div className="text-sm font-medium text-fg">Agent internet kill switch</div>
      <p className="mt-1 text-xs text-fg-muted">
        While engaged, the web_search and fetch_url tools refuse every call from every agent, immediately,
        including runs in progress. Only you can change it; agents have no tool that reads or writes it.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className={primaryButtonClasses}
          disabled={setBlocked.isPending}
          onClick={() => setBlocked.mutate(!data.blocked)}
        >
          {data.blocked ? 'Re-enable agent internet access' : 'Block all agent internet access'}
        </button>
        <span className="text-xs text-fg-muted">
          {data.blocked ? 'Engaged: agents cannot reach the internet.' : 'Released: agents with web tools can search.'}
        </span>
      </div>
    </Card>
  )
}

function AiModeCard() {
  return (
    <Card className="p-4">
      <div className="text-sm font-medium text-fg">AI Mode</div>
      <p className="mt-1 text-xs text-fg-muted">
        The Ollama-driven discovery agent now has its own section: run it, tune its model and prompt, and
        inspect every step it takes.
      </p>
      <Link to="/ai" className="mt-3 inline-block text-sm font-medium text-accent-strong hover:underline">
        Open AI Mode
      </Link>
    </Card>
  )
}

function TelegramCard() {
  const { data: config } = useTelegramConfig()
  const update = useUpdateTelegramConfig()
  const test = useTelegramTest()
  const [token, setToken] = useState('')
  const [chatIds, setChatIds] = useState<string | null>(null)
  if (!config) return null
  const chatText = chatIds ?? config.chat_ids.join(', ')

  function save(patch: TelegramUpdate = {}) {
    const ids = chatText
      .split(/[\s,]+/)
      .filter(Boolean)
      .map(Number)
    update.mutate(
      { bot_token: token || undefined, chat_ids: ids.filter((n) => Number.isInteger(n)), ...patch },
      {
        onSuccess: () => {
          setToken('')
          setChatIds(null)
        },
      },
    )
  }

  return (
    <Card className="p-4">
      <form
        id="telegram-form"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <SaveBar
          title="Telegram"
          description="Talk to the assistant from Telegram, ask for reports as PDF and receive alerts. The bot polls Telegram, so no inbound port is needed."
          saving={update.isPending}
          saved={update.isSuccess}
          error={update.error?.message ?? null}
        />
        <div className="mt-4 flex flex-col gap-4">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => save({ enabled: e.target.checked })}
            />
            Enable the bot
          </label>
          <label className="flex flex-col text-sm">
            Bot token {config.token_set && <span className="text-xs text-fg-muted">(saved; paste a new one to replace it)</span>}
            <input
              type="password"
              autoComplete="off"
              className={`${inputClasses} max-w-md`}
              placeholder="From @BotFather"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <label className="flex flex-col text-sm">
            Allowed chat ids
            <input
              className={`${inputClasses} max-w-md`}
              placeholder="123456789"
              value={chatText}
              onChange={(e) => setChatIds(e.target.value)}
            />
            <span className="mt-1 text-xs text-fg-muted">
              Message your bot once; it replies with your chat id. Only these chats get answers.
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={config.notify_alerts}
              onChange={(e) => save({ notify_alerts: e.target.checked })}
            />
            Send alert changes to these chats
          </label>
          <div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={config.notify_ai_reports}
                onChange={(e) => save({ notify_ai_reports: e.target.checked })}
              />
              Send AI-generated reports to these chats automatically
            </label>
            <span className="mt-1 block text-xs text-fg-muted">
              Covers every way a report gets saved - an explicit /report ai, a scheduled run, or an
              agent escalation chain (e.g. reviewer finds something, the team investigates, reporter
              writes it up). Off: the report is still saved on the Reports page, just not pushed here.
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50"
              disabled={test.isPending || !config.enabled}
              onClick={() => test.mutate()}
            >
              Send test message
            </button>
            {test.isSuccess && <span className="text-xs text-fg-muted">Sent.</span>}
            {test.error && <span className="text-xs text-red-600 dark:text-red-400">{test.error.message}</span>}
          </div>
        </div>
      </form>
    </Card>
  )
}

function AccountCard() {
  return (
    <Card className="p-4">
      <div className="text-sm font-medium text-fg">Account</div>
      <p className="mb-4 mt-1 text-xs text-fg-muted">
        Change the password of the admin account. Signing in elsewhere is ended when you do. Any non-empty
        password is accepted.
      </p>
      <div className="max-w-sm">
        <ChangePasswordForm />
      </div>
    </Card>
  )
}

export function SystemPage() {
  const { data: settings, isLoading } = useDiscoverySettings()

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Discovery scanning, nmap fingerprinting, AI Mode, Telegram and your account."
      />
      <div className="mt-6 flex flex-col gap-6">
        {isLoading && <div className="text-sm text-fg-muted">Loading...</div>}
        {settings && (
          <>
            <ScanCard settings={settings} />
            <AiModeCard />
            <InternetKillSwitchCard />
            <TelegramCard />
            <AccountCard />
          </>
        )}
      </div>
    </div>
  )
}
