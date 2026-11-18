import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useDeleteIntegration, useForgetHostKey, useIntegrations, useSetIntegrationEnabled, type Integration } from '../api/integrations'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { IntegrationForm, type IntegrationPrefill } from '../components/IntegrationForm'
import { DeleteIcon, EditIcon, KeyIcon, ToggleIcon } from '../components/icons'

interface PrefillIntegrationState {
  prefillIntegration?: IntegrationPrefill
}

const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95'

/** The Integrations tab: the configured integrations, with add and edit opening the form in place. */
export function IntegrationsPage() {
  const location = useLocation()
  const prefill = (location.state as PrefillIntegrationState | null)?.prefillIntegration
  const { data: integrations, isLoading } = useIntegrations()
  const deleteIntegration = useDeleteIntegration()
  const forgetHostKey = useForgetHostKey()
  const setEnabled = useSetIntegrationEnabled()

  // Arriving from Discovery's "Configure as" link opens the add form already filled in.
  const [mode, setMode] = useState<'list' | 'add' | { edit: Integration }>(prefill ? 'add' : 'list')

  return (
    <div>
      {mode === 'list' ? (
        <div className="flex justify-end">
          <button type="button" className={primaryButtonClasses} onClick={() => setMode('add')}>
            New integration
          </button>
        </div>
      ) : (
        <IntegrationForm
          key={mode === 'add' ? 'add' : mode.edit.id}
          integration={mode === 'add' ? undefined : mode.edit}
          prefill={mode === 'add' ? prefill : undefined}
          onDone={() => setMode('list')}
        />
      )}

      <div className="mt-4">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-left text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Host</th>
                <th className="px-4 py-2.5 font-medium">Enabled</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={6}>
                    Loading…
                  </td>
                </tr>
              )}
              {integrations?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={6}>
                    No integrations configured yet.
                  </td>
                </tr>
              )}
              {integrations?.map((integration) => {
                const host = integration.config.host
                return (
                <tr key={integration.id} className="border-b border-line align-middle last:border-b-0">
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">{integration.name}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-fg-muted">{integration.integration_type}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    {typeof host === 'string' && host ? (
                      host
                    ) : (
                      <span title="No host set: this credential is tried against any matching host discovery finds.">
                        <Badge tone="neutral">Any discovered host</Badge>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={integration.enabled ? 'ok' : 'neutral'}>{integration.enabled ? 'Enabled' : 'Disabled'}</Badge>
                  </td>
                  <td className="px-4 py-2.5" title={integration.last_error ?? undefined}>
                    <Badge tone={integration.status === 'ok' ? 'ok' : integration.status === 'error' ? 'bad' : 'neutral'}>
                      {integration.status}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <div className="inline-flex items-center justify-end gap-4">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs font-medium text-accent-strong hover:underline"
                        title="Change this integration's name, config or credential."
                        onClick={() => setMode({ edit: integration })}
                      >
                        <EditIcon />
                        Edit
                      </button>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs font-medium text-accent-strong hover:underline disabled:opacity-50"
                        title={
                          integration.enabled
                            ? 'Disable: pauses polling (or, for a wallet entry, trying this credential against discovered hosts) without deleting it.'
                            : 'Enable: resumes polling (or wallet probing).'
                        }
                        disabled={setEnabled.isPending}
                        onClick={() =>
                          setEnabled.mutate({ id: integration.id, enabled: !integration.enabled })
                        }
                      >
                        <ToggleIcon />
                        {integration.enabled ? 'Disable' : 'Enable'}
                      </button>
                      {integration.integration_type === 'generic_ssh' && integration.config.host_key != null && (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 text-xs font-medium text-accent-strong hover:underline disabled:opacity-50"
                          title="The host's SSH key is pinned. Forget it if the host was reinstalled; the next poll pins its new key."
                          disabled={forgetHostKey.isPending}
                          onClick={() => {
                            if (window.confirm(`Forget the pinned SSH host key of ${integration.name}?`)) {
                              forgetHostKey.mutate(integration.id)
                            }
                          }}
                        >
                          <KeyIcon />
                          Forget pinned key
                        </button>
                      )}
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline"
                        title="Delete this integration and its scheduled polling. The stored credential, if any, is not deleted - manage it from Credentials."
                        onClick={() => {
                          if (window.confirm(`Delete the integration "${integration.name}"? This cannot be undone.`)) {
                            deleteIntegration.mutate(integration.id)
                          }
                        }}
                      >
                        <DeleteIcon />
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
