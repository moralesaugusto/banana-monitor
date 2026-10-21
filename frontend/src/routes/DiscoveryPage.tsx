import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useAcceptService,
  useDiscoveredCandidates,
  useIgnoreCandidate,
  type DiscoveredCandidate,
} from '../api/discovery'
import { useDiscoverySettings, useUpdateDiscoverySettings } from '../api/system'
import { SERVICE_TYPES, type ServiceType } from '../api/types'
import { Badge } from '../components/Badge'
import { SshHostKeysCard } from '../components/SshHostKeysCard'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

const selectClasses = 'rounded-control border border-line bg-surface px-2 py-1 text-xs text-fg'
const acceptButtonClasses = 'rounded-control bg-accent px-2 py-1 text-xs font-medium text-on-accent hover:brightness-95'

/** Friendly labels for a discovery probe's best-effort product guess
 * (raw_attributes.suggested_integration_type) - see docs/integrations.md's
 * fingerprinting section. Never a hard classification. */
const SUGGESTION_LABELS: Record<string, string> = {
  generic_ssh: 'Generic (SSH)',
  adguard_home: 'AdGuard Home',
  homebridge: 'Homebridge',
  omada: 'TP-Link Omada',
}

type ServiceCandidateAttrs = {
  ip?: string
  port?: number
  protocol?: string
  http?: { server?: string; title?: string; status_code?: string }
  tls?: { common_name?: string; not_after?: string }
  suggested_integration_type?: string
  /** Plain TCP banner read on connect (SSH/FTP/SMTP/etc.) - pure Python,
   * always attempted for a non-HTTP/TLS open port, no nmap involved. */
  banner?: string
  /** Best-effort `nmap -sV` product/version guess for this port, only
   * present when nmap OS detection is enabled (opt-in, see
   * docs/discovery.md) - a second opinion alongside the HTTP-probe-based
   * `http`/`suggested_integration_type` fields above. */
  nmap_service?: { product?: string; version?: string; extrainfo?: string }
}

/** Same default guess shown pre-selected in each row's type dropdown - the
 * single source of truth for both an individual "Accept" and "Accept all". */
function defaultServiceType(attrs: ServiceCandidateAttrs): ServiceType {
  return attrs.protocol === 'https' ? 'https' : attrs.protocol === 'http' ? 'http' : 'tcp'
}

function defaultAcceptPayload(candidate: DiscoveredCandidate) {
  const attrs = candidate.raw_attributes as ServiceCandidateAttrs
  const serviceType = defaultServiceType(attrs)
  const config =
    serviceType === 'tcp'
      ? { host: attrs.ip, port: attrs.port }
      : { url: `${serviceType}://${attrs.ip}:${attrs.port}` }
  return { candidateId: candidate.id, serviceType, config }
}

function ServiceCandidateRow({ candidate }: { candidate: DiscoveredCandidate }) {
  const acceptService = useAcceptService()
  const ignore = useIgnoreCandidate()
  const attrs = candidate.raw_attributes as ServiceCandidateAttrs
  const [serviceType, setServiceType] = useState<ServiceType>(defaultServiceType(attrs))

  const suggestedIntegration = attrs.suggested_integration_type
  const suggestionLabel = suggestedIntegration
    ? (SUGGESTION_LABELS[suggestedIntegration] ?? suggestedIntegration)
    : null

  function handleAccept() {
    const config =
      serviceType === 'tcp'
        ? { host: attrs.ip, port: attrs.port }
        : { url: `${serviceType}://${attrs.ip}:${attrs.port}` }
    acceptService.mutate({ candidateId: candidate.id, serviceType, config })
  }

  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-2.5 align-top">
        <Badge tone="neutral">Service</Badge>
      </td>
      <td className="px-4 py-2.5 align-top">
        <div className="font-mono">
          {attrs.ip}:{attrs.port} <span className="text-fg-muted">({attrs.protocol})</span>
        </div>
        {attrs.http?.title && <div className="text-xs text-fg-muted">{attrs.http.title}</div>}
        {attrs.tls?.common_name && (
          <div className="text-xs text-fg-muted">TLS CN: {attrs.tls.common_name}</div>
        )}
        {attrs.banner && (
          <div className="truncate text-xs text-fg-muted" title={attrs.banner}>
            banner: {attrs.banner}
          </div>
        )}
        {attrs.nmap_service?.product && (
          <div className="text-xs text-fg-muted">
            nmap: {attrs.nmap_service.product}
            {attrs.nmap_service.version && ` ${attrs.nmap_service.version}`}
          </div>
        )}
        {suggestionLabel && (
          <div className="mt-1">
            <Badge tone="info">Looks like: {suggestionLabel}</Badge>
          </div>
        )}
      </td>
      <td className="px-4 py-2.5 align-top text-xs text-fg-muted">
        seen {candidate.times_seen}x, via {candidate.discovered_via}
      </td>
      <td className="px-4 py-2.5 align-top">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className={selectClasses}
            value={serviceType}
            onChange={(e) => setServiceType(e.target.value as ServiceType)}
          >
            {SERVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <button type="button" className={acceptButtonClasses} onClick={handleAccept}>
            Accept
          </button>
          <button
            type="button"
            className="text-xs text-fg-muted hover:underline"
            onClick={() => ignore.mutate(candidate.id)}
          >
            Ignore
          </button>
          {suggestedIntegration && (
            <Link
              to="/integrations"
              state={{
                prefillIntegration: { type_key: suggestedIntegration, host: attrs.ip, port: attrs.port },
              }}
              className="text-xs font-medium text-accent-strong hover:underline"
            >
              Configure as {suggestionLabel}
            </Link>
          )}
        </div>
      </td>
    </tr>
  )
}

function AutoAcceptToggle() {
  const { data: settings } = useDiscoverySettings()
  const update = useUpdateDiscoverySettings()
  if (!settings) return null
  return (
    <label
      className="mt-4 flex items-center gap-2 text-sm"
      title="New services are accepted and monitored as soon as they are seen, without waiting for review. Ignored services stay ignored."
    >
      <input
        type="checkbox"
        checked={settings.auto_accept_services}
        disabled={update.isPending}
        onChange={(e) => update.mutate({ auto_accept_services: e.target.checked })}
      />
      Automatically accept services as they are discovered
    </label>
  )
}

export function DiscoveryPage() {
  const { data: candidates, isLoading } = useDiscoveredCandidates()
  const acceptService = useAcceptService()
  const [acceptingAll, setAcceptingAll] = useState(false)

  async function handleAcceptAll() {
    if (!candidates || candidates.length === 0) return
    setAcceptingAll(true)
    try {
      // Sequential, not Promise.all: each acceptance invalidates and refetches
      // the candidates list, and the backend registers the new Service with
      // the live scheduler one at a time anyway - no need to race that.
      for (const candidate of candidates) {
        await acceptService.mutateAsync(defaultAcceptPayload(candidate))
      }
    } finally {
      setAcceptingAll(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Discovery"
        description="Services seen on your networks, waiting for review. Accept to start monitoring them, or ignore to suppress. Unre-seen candidates expire automatically after 30 days. Devices are populated automatically as they're seen — see the Devices page."
        actions={
          <button
            type="button"
            className="rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50"
            onClick={handleAcceptAll}
            disabled={acceptingAll || !candidates || candidates.length === 0}
          >
            {acceptingAll ? 'Accepting…' : `Accept all (${candidates?.length ?? 0})`}
          </button>
        }
      />

      <AutoAcceptToggle />

      <div className="mt-6 overflow-x-auto">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Kind</th>
                <th className="px-4 py-2.5 font-medium">Details</th>
                <th className="px-4 py-2.5 font-medium">Seen</th>
                <th className="px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    Loading…
                  </td>
                </tr>
              )}
              {candidates?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={4}>
                    Nothing pending review. Trigger a scan from the Networks page.
                  </td>
                </tr>
              )}
              {/* Device candidates auto-provision into real Devices on first
                  observation now (see docs/decisions.md), so this queue only
                  ever holds service candidates. */}
              {candidates?.map((candidate) => (
                <ServiceCandidateRow key={candidate.id} candidate={candidate} />
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <SshHostKeysCard />
    </div>
  )
}
