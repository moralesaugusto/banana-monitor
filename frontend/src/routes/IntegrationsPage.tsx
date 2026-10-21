import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useCreateCredential, useCredentials, type CredentialType } from '../api/credentials'
import { useDevices } from '../api/devices'
import {
  useCreateIntegration,
  useDeleteIntegration,
  useForgetHostKey,
  useIntegrationTypes,
  useIntegrations,
  useSetIntegrationEnabled,
  type IntegrationTypeInfo,
} from '../api/integrations'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { DeleteIcon, KeyIcon, ToggleIcon } from '../components/icons'
import { PageHeader } from '../components/PageHeader'
import { SchemaFieldsForm } from '../components/SchemaForm'
import { defaultValuesForSchema, parseObjectSchema, schemaValuesComplete } from '../lib/schemaForm'

interface PrefillIntegrationState {
  prefillIntegration?: {
    type_key: string
    host?: string
    port?: number
  }
}

/** The credential shape each built-in plugin's credential_schema actually asks for - used to pick a
 * sensible credential_type without making the user choose one that duplicates the integration Type
 * they already picked above. Falls back to api_token for an unknown future plugin. */
const CREDENTIAL_TYPE_FOR_INTEGRATION: Record<string, CredentialType> = {
  generic_ssh: 'ssh_key',
  proxmox: 'api_token',
  adguard_home: 'basic_auth',
  homebridge: 'basic_auth',
  omada: 'basic_auth',
  windows_winrm: 'basic_auth',
  virustotal: 'api_token',
}

/** generic_ssh takes either a private key or a password (see SshCredential on the backend) - label the
 * saved credential by whichever one was actually filled in, instead of a fixed guess. */
function credentialTypeFor(typeKey: string, secret?: Record<string, unknown>): CredentialType {
  if (typeKey === 'generic_ssh' && secret && !secret.private_key && secret.password) return 'ssh_password'
  return CREDENTIAL_TYPE_FOR_INTEGRATION[typeKey] ?? 'api_token'
}

/** One-line, plain-language summary of what each built-in plugin monitors - shown under the Type
 * picker. See the Integrations "How it works" page for the longer version. */
const INTEGRATION_TYPE_HELP: Record<string, string> = {
  http_tcp: 'Checks that an HTTP(S) URL or a raw TCP port answers. No credential needed.',
  generic_ssh: 'Load, memory and disk usage over SSH, read-only. Needs an SSH username + private key or password.',
  proxmox: 'Discovers and polls Proxmox nodes, VMs and LXCs. Needs an API token (id + value).',
  dns: 'Resolves a DNS query against a resolver, to confirm it answers. No credential needed.',
  dhcp: 'Best-effort check that a DHCP server replies to a discover. No credential needed.',
  adguard_home: 'Query/blocking stats and protection state. Needs the AdGuard Home web UI login.',
  homebridge: 'Accessory count and host metrics via the Homebridge UI. Needs its login.',
  omada: 'Client and device counts from a TP-Link Omada controller. Needs its login.',
  windows_winrm: 'CPU, memory and disk usage over WinRM, read-only. Needs a Windows username + password.',
  virustotal: "Doesn't monitor anything - stores an API key for the AI agents' lookup tool.",
}

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'self-start rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

export function IntegrationsPage() {
  const location = useLocation()
  const { data: types } = useIntegrationTypes()
  const { data: integrations, isLoading } = useIntegrations()
  const { data: credentials } = useCredentials()
  const { data: devices } = useDevices()
  const createIntegration = useCreateIntegration()
  const deleteIntegration = useDeleteIntegration()
  const forgetHostKey = useForgetHostKey()
  const setEnabled = useSetIntegrationEnabled()
  const createCredential = useCreateCredential()

  const [integrationType, setIntegrationType] = useState('')
  const [name, setName] = useState('')
  const [configText, setConfigText] = useState('{}')
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [credentialId, setCredentialId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const [showNewCredential, setShowNewCredential] = useState(false)
  const [newCredLabel, setNewCredLabel] = useState('')
  const [newCredSecretText, setNewCredSecretText] = useState('{}')
  const [credentialValues, setCredentialValues] = useState<Record<string, unknown>>({})

  const selectedTypeInfo: IntegrationTypeInfo | undefined = types?.find((t) => t.type_key === integrationType)
  const parsedConfigSchema = selectedTypeInfo ? parseObjectSchema(selectedTypeInfo.config_schema) : null
  const parsedCredentialSchema = selectedTypeInfo?.credential_schema
    ? parseObjectSchema(selectedTypeInfo.credential_schema)
    : null

  const prefillApplied = useRef(false)
  useEffect(() => {
    if (prefillApplied.current || !types || types.length === 0) return
    const state = location.state as PrefillIntegrationState | null
    const prefill = state?.prefillIntegration
    if (!prefill) return
    const info = types.find((t) => t.type_key === prefill.type_key)
    if (!info) return

    prefillApplied.current = true
    setIntegrationType(info.type_key)
    const parsed = parseObjectSchema(info.config_schema)
    const defaults = parsed ? defaultValuesForSchema(parsed) : {}
    setConfigValues({
      ...defaults,
      ...(prefill.host ? { host: prefill.host } : {}),
      ...(prefill.port ? { port: prefill.port } : {}),
    })
  }, [location.state, types])

  function handleTypeChange(typeKey: string) {
    setIntegrationType(typeKey)
    const info = types?.find((t) => t.type_key === typeKey)
    const parsedConfig = info ? parseObjectSchema(info.config_schema) : null
    setConfigValues(parsedConfig ? defaultValuesForSchema(parsedConfig) : {})
    setConfigText('{}')
    const parsedCred = info?.credential_schema ? parseObjectSchema(info.credential_schema) : null
    setCredentialValues(parsedCred ? defaultValuesForSchema(parsedCred) : {})
    setNewCredSecretText('{}')
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    let config: Record<string, unknown>
    if (parsedConfigSchema) {
      if (!schemaValuesComplete(parsedConfigSchema, configValues)) {
        setError('Fill in all required config fields.')
        return
      }
      config = configValues
    } else {
      try {
        config = JSON.parse(configText)
      } catch {
        setError('Config must be valid JSON.')
        return
      }
    }

    let resolvedCredentialId = credentialId ? Number(credentialId) : null

    if (showNewCredential) {
      let secret: Record<string, unknown>
      if (parsedCredentialSchema) {
        if (!schemaValuesComplete(parsedCredentialSchema, credentialValues)) {
          setError('Fill in all required credential fields.')
          return
        }
        secret = credentialValues
      } else {
        try {
          secret = JSON.parse(newCredSecretText)
        } catch {
          setError('Credential secret must be valid JSON.')
          return
        }
      }
      try {
        const credential = await createCredential.mutateAsync({
          label: newCredLabel,
          credential_type: credentialTypeFor(integrationType, secret),
          secret,
        })
        resolvedCredentialId = credential.id
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create credential.')
        return
      }
    }

    try {
      await createIntegration.mutateAsync({
        integration_type: integrationType,
        name,
        config,
        credential_id: resolvedCredentialId,
      })
      setName('')
      setConfigText('{}')
      setConfigValues(parsedConfigSchema ? defaultValuesForSchema(parsedConfigSchema) : {})
      setCredentialId('')
      setShowNewCredential(false)
      setNewCredLabel('')
      setNewCredSecretText('{}')
      setCredentialValues({})
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create integration.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Integrations"
        description={
          <>
            Configured integrations and their credentials. Selecting a type below renders that plugin's
            own config/credential fields. Leave Host empty to save a credential in the{' '}
            <Link to="/integrations/learn" className="text-accent-strong hover:underline">
              wallet
            </Link>{' '}
            instead — see{' '}
            <Link to="/integrations/learn" className="text-accent-strong hover:underline">
              how it works
            </Link>
            . Manage saved credentials on the{' '}
            <Link to="/integrations/credentials" className="text-accent-strong hover:underline">
              Credentials
            </Link>{' '}
            page.
          </>
        }
      />

      <form
        onSubmit={handleSubmit}
        className="mt-6 flex flex-col gap-4 rounded-card border border-line bg-surface p-4"
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col text-sm">
            Type
            {types && types.length > 0 ? (
              <select
                className={inputClasses}
                value={integrationType}
                onChange={(e) => handleTypeChange(e.target.value)}
              >
                <option value="">Select…</option>
                {types.map((t) => (
                  <option key={t.type_key} value={t.type_key}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={inputClasses}
                value={integrationType}
                onChange={(e) => setIntegrationType(e.target.value)}
                placeholder="proxmox"
              />
            )}
            {INTEGRATION_TYPE_HELP[integrationType] && (
              <span className="mt-1 text-xs text-fg-subtle">{INTEGRATION_TYPE_HELP[integrationType]}</span>
            )}
          </label>
          <label className="flex flex-col text-sm">
            Name
            <input
              className={inputClasses}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="pve1"
            />
          </label>
        </div>

        {parsedConfigSchema ? (
          <div>
            <div className="text-sm text-fg-muted">Config</div>
            <div className="mt-1">
              <SchemaFieldsForm
                parsed={parsedConfigSchema}
                values={configValues}
                onChange={setConfigValues}
                idPrefix="config"
                devices={devices}
              />
            </div>
          </div>
        ) : (
          <label className="flex flex-col text-sm">
            Config (JSON)
            <textarea
              className={`${inputClasses} font-mono text-xs`}
              rows={3}
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
            />
          </label>
        )}

        <div>
          <label className="flex flex-col text-sm">
            Credential
            <select
              className={inputClasses}
              value={credentialId}
              onChange={(e) => setCredentialId(e.target.value)}
              disabled={showNewCredential}
            >
              <option value="">None</option>
              {credentials?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} ({c.credential_type})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="mt-1 text-xs text-accent-strong hover:underline"
            onClick={() => setShowNewCredential((v) => !v)}
          >
            {showNewCredential ? 'Cancel new credential' : '+ New credential'}
          </button>
        </div>

        {showNewCredential && (
          <div className="flex flex-col gap-2 rounded-control bg-canvas p-3">
            <label className="flex flex-col text-sm sm:max-w-[calc(50%-0.375rem)]">
              Label
              <input
                className={inputClasses}
                value={newCredLabel}
                onChange={(e) => setNewCredLabel(e.target.value)}
                placeholder="pve1-token"
              />
              <span className="mt-1 text-xs text-fg-subtle">
                Saved as a {credentialTypeFor(integrationType, credentialValues)} credential for the integration
                Type above.
              </span>
            </label>
            {parsedCredentialSchema ? (
              <div>
                <div className="text-sm text-fg-muted">Secret — never shown again after saving</div>
                <div className="mt-1">
                  <SchemaFieldsForm
                    parsed={parsedCredentialSchema}
                    values={credentialValues}
                    onChange={setCredentialValues}
                    idPrefix="credential"
                  />
                </div>
              </div>
            ) : (
              <label className="flex flex-col text-sm">
                Secret (JSON — never shown again after saving)
                <textarea
                  className={`${inputClasses} font-mono text-xs`}
                  rows={2}
                  value={newCredSecretText}
                  onChange={(e) => setNewCredSecretText(e.target.value)}
                />
              </label>
            )}
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={createIntegration.isPending || createCredential.isPending}
          className={primaryButtonClasses}
        >
          Add integration
        </button>
      </form>

      <div className="mt-6">
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
                        <Badge tone="neutral">Wallet</Badge>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={integration.enabled ? 'ok' : 'neutral'}>{integration.enabled ? 'Enabled' : 'Disabled'}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={integration.status === 'ok' ? 'ok' : integration.status === 'error' ? 'bad' : 'neutral'}>
                      {integration.status}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <div className="inline-flex items-center justify-end gap-4">
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
