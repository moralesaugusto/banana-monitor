import { useEffect, useRef, useState } from 'react'
import { useCreateCredential, useCredentials } from '../api/credentials'
import { useDevices } from '../api/devices'
import {
  useCreateIntegration,
  useIntegrationTypes,
  useUpdateIntegration,
  type Integration,
  type IntegrationTypeInfo,
} from '../api/integrations'
import { credentialTypeFor } from '../lib/credentialTypes'
import { defaultValuesForSchema, parseObjectSchema, schemaValuesComplete } from '../lib/schemaForm'
import { SchemaFieldsForm } from './SchemaForm'

export interface IntegrationPrefill {
  type_key: string
  host?: string
  port?: number
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
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'
const secondaryButtonClasses =
  'rounded-control border border-line px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'

/** Creates an integration, or - when `integration` is given - edits one (its type is fixed). */
export function IntegrationForm({
  integration,
  prefill,
  onDone,
}: {
  integration?: Integration
  prefill?: IntegrationPrefill
  onDone: () => void
}) {
  const { data: types } = useIntegrationTypes()
  const { data: credentials } = useCredentials()
  const { data: devices } = useDevices()
  const createIntegration = useCreateIntegration()
  const updateIntegration = useUpdateIntegration()
  const createCredential = useCreateCredential()
  const editing = integration !== undefined

  const [integrationType, setIntegrationType] = useState(integration?.integration_type ?? '')
  const [name, setName] = useState(integration?.name ?? '')
  const [configText, setConfigText] = useState(integration ? JSON.stringify(integration.config, null, 2) : '{}')
  const [configValues, setConfigValues] = useState<Record<string, unknown>>(integration?.config ?? {})
  const [credentialId, setCredentialId] = useState<string>(integration?.credential_id?.toString() ?? '')
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
    if (integration && !prefillApplied.current && selectedTypeInfo) {
      // Editing: show the schema defaults (port, interval, ...) under what is stored, as the add form does.
      prefillApplied.current = true
      const parsed = parseObjectSchema(selectedTypeInfo.config_schema)
      if (parsed) setConfigValues({ ...defaultValuesForSchema(parsed), ...integration.config })
      return
    }
    if (prefillApplied.current || !prefill || !types || types.length === 0) return
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
  }, [prefill, types, integration, selectedTypeInfo])

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
      if (integration) {
        await updateIntegration.mutateAsync({ id: integration.id, name, config, credential_id: resolvedCredentialId })
      } else {
        await createIntegration.mutateAsync({
          integration_type: integrationType,
          name,
          config,
          credential_id: resolvedCredentialId,
        })
      }
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${editing ? 'save' : 'create'} integration.`)
    }
  }

  const pending = createIntegration.isPending || updateIntegration.isPending || createCredential.isPending

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
      <h2 className="text-base font-medium">{editing ? `Edit ${integration.name}` : 'New integration'}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col text-sm">
          Type
          {types && types.length > 0 ? (
            <select
              className={inputClasses}
              value={integrationType}
              disabled={editing}
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
              disabled={editing}
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
          <input className={inputClasses} value={name} onChange={(e) => setName(e.target.value)} placeholder="pve1" />
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
              Saved as a {credentialTypeFor(integrationType, credentialValues)} credential for the integration Type
              above.
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

      <div className="flex items-center gap-2">
        <button type="submit" disabled={pending} className={primaryButtonClasses}>
          {editing ? 'Save changes' : 'Add integration'}
        </button>
        <button type="button" className={secondaryButtonClasses} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}
