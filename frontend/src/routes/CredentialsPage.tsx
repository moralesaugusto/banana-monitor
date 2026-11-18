import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  useUpdateCredential,
  type Credential,
  type CredentialType,
} from '../api/credentials'
import { useIntegrationTypes, type IntegrationTypeInfo } from '../api/integrations'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { DeleteIcon, EditIcon } from '../components/icons'
import { SchemaFieldsForm } from '../components/SchemaForm'
import { credentialTypeFor, defaultTypeForCredential, typesWithCredentials } from '../lib/credentialTypes'
import { defaultValuesForSchema, parseObjectSchema, schemaValuesComplete } from '../lib/schemaForm'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'
const secondaryButtonClasses =
  'rounded-control border border-line px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'

const JSON_FORMAT = ''
/** A single API key, stored as {token}: how the OpenRouter / LLM keys used by the AI agents and the chat
 * assistant are saved. Not an integration type, so it is offered alongside them. */
const API_KEY_FORMAT = '__api_key'

/** Secret entry: pick a layout (an integration type's own fields, or raw JSON) and fill it in.
 * Reports the secret and the credential type that layout implies, or null while incomplete. */
function SecretFields({
  initialType,
  onChange,
}: {
  initialType: string
  onChange: (value: { secret: Record<string, unknown>; credentialType: CredentialType } | null) => void
}) {
  const { data: types } = useIntegrationTypes()
  const options = typesWithCredentials(types)
  const [format, setFormat] = useState(initialType)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [jsonText, setJsonText] = useState('{}')

  const [apiKey, setApiKey] = useState('')

  const info = options.find((t) => t.type_key === format)
  const parsed = info?.credential_schema ? parseObjectSchema(info.credential_schema) : null

  function report(nextFormat: string, nextValues: Record<string, unknown>, nextJson: string, nextKey = apiKey) {
    if (nextFormat === API_KEY_FORMAT) {
      onChange(nextKey.trim() ? { secret: { token: nextKey }, credentialType: 'api_token' } : null)
      return
    }
    const nextInfo = options.find((t) => t.type_key === nextFormat)
    const nextParsed = nextInfo?.credential_schema ? parseObjectSchema(nextInfo.credential_schema) : null
    if (nextParsed) {
      onChange(
        schemaValuesComplete(nextParsed, nextValues)
          ? { secret: nextValues, credentialType: credentialTypeFor(nextFormat, nextValues) }
          : null,
      )
      return
    }
    try {
      onChange({ secret: JSON.parse(nextJson), credentialType: 'api_token' })
    } catch {
      onChange(null)
    }
  }

  function changeFormat(next: string) {
    const nextInfo = options.find((t) => t.type_key === next)
    const nextParsed = nextInfo?.credential_schema ? parseObjectSchema(nextInfo.credential_schema) : null
    const nextValues = nextParsed ? defaultValuesForSchema(nextParsed) : {}
    setFormat(next)
    setValues(nextValues)
    report(next, nextValues, jsonText)
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col text-sm sm:max-w-[calc(50%-0.375rem)]">
        Secret fields for
        <select className={inputClasses} value={format} onChange={(e) => changeFormat(e.target.value)}>
          <option value={API_KEY_FORMAT}>API key (OpenRouter, LLM providers)</option>
          <option value={JSON_FORMAT}>Custom (JSON)</option>
          {options.map((t) => (
            <option key={t.type_key} value={t.type_key}>
              {t.display_name}
            </option>
          ))}
        </select>
      </label>
      {format === API_KEY_FORMAT ? (
        <label className="flex flex-col text-sm sm:max-w-[calc(50%-0.375rem)]">
          API key
          <input
            type="password"
            autoComplete="off"
            className={inputClasses}
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value)
              report(format, values, jsonText, e.target.value)
            }}
          />
        </label>
      ) : parsed ? (
        <SchemaFieldsForm
          parsed={parsed}
          values={values}
          onChange={(next) => {
            setValues(next)
            report(format, next, jsonText)
          }}
          idPrefix="secret"
        />
      ) : (
        <label className="flex flex-col text-sm">
          Secret (JSON)
          <textarea
            className={`${inputClasses} font-mono text-xs`}
            rows={3}
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value)
              report(format, values, e.target.value)
            }}
          />
        </label>
      )}
    </div>
  )
}

function PoolCheckbox({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        Include in the agents' credential pool
      </label>
      <p className="mt-1 text-xs text-fg-subtle">
        Agents set to use the pool (on each agent's page) may try this credential on hosts that have no integration of
        their own. Off by default. SSH credentials are tried for SSH, basic-auth for WinRM, API tokens for Proxmox.
      </p>
    </div>
  )
}

function AddCredentialForm({ onDone }: { onDone: () => void }) {
  const create = useCreateCredential()
  const [label, setLabel] = useState('')
  const [inPool, setInPool] = useState(false)
  const [entered, setEntered] = useState<{ secret: Record<string, unknown>; credentialType: CredentialType } | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!entered) {
      setError('Fill in all required secret fields.')
      return
    }
    setError(null)
    try {
      await create.mutateAsync({
        label,
        credential_type: entered.credentialType,
        secret: entered.secret,
        in_agent_pool: inPool,
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create credential.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
      <h2 className="text-base font-medium">New credential</h2>
      <label className="flex flex-col text-sm sm:max-w-[calc(50%-0.375rem)]">
        Label
        <input className={inputClasses} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="pve1-token" />
      </label>
      <SecretFields initialType="" onChange={setEntered} />
      <PoolCheckbox checked={inPool} onChange={setInPool} />
      <p className="text-xs text-fg-subtle">The secret is encrypted on save and never shown again.</p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button type="submit" className={primaryButtonClasses} disabled={create.isPending || !label.trim()}>
          Add credential
        </button>
        <button type="button" className={secondaryButtonClasses} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

/** Keys used by something other than an integration (the chat assistant, an agent, the default LLM,
 * Telegram) are a single API key; otherwise guess the layout from the credential's type. */
function initialSecretFormat(types: IntegrationTypeInfo[] | undefined, credential: Credential): string {
  const usedOutsideIntegrations = credential.used_by.some((user) => !user.startsWith('integration '))
  return usedOutsideIntegrations ? API_KEY_FORMAT : defaultTypeForCredential(types, credential.credential_type)
}

function EditCredentialForm({ credential, onDone }: { credential: Credential; onDone: () => void }) {
  const update = useUpdateCredential()
  const { data: types } = useIntegrationTypes()
  const [label, setLabel] = useState(credential.label)
  const [inPool, setInPool] = useState(credential.in_agent_pool ?? false)
  const [replace, setReplace] = useState(false)
  const [entered, setEntered] = useState<{ secret: Record<string, unknown>; credentialType: CredentialType } | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (replace && !entered) {
      setError('Fill in all required secret fields.')
      return
    }
    setError(null)
    try {
      await update.mutateAsync({
        id: credential.id,
        label,
        in_agent_pool: inPool,
        ...(replace && entered ? { secret: entered.secret } : {}),
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save credential.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
      <h2 className="text-base font-medium">Edit {credential.label}</h2>
      <label className="flex flex-col text-sm sm:max-w-[calc(50%-0.375rem)]">
        Label
        <input className={inputClasses} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {replace ? (
        <>
          <SecretFields initialType={initialSecretFormat(types, credential)} onChange={setEntered} />
          <p className="text-xs text-fg-subtle">
            The new secret replaces the stored one entirely; the old one is not shown or recoverable. Everything using this
            credential picks it up on its next run.
          </p>
        </>
      ) : (
        <div>
          <button type="button" className="text-sm text-accent-strong hover:underline" onClick={() => setReplace(true)}>
            Replace secret
          </button>
          <p className="mt-1 text-xs text-fg-subtle">The stored secret is never displayed. Leave it to keep it unchanged.</p>
        </div>
      )}
      <PoolCheckbox checked={inPool} onChange={setInPool} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button type="submit" className={primaryButtonClasses} disabled={update.isPending || !label.trim()}>
          Save changes
        </button>
        <button type="button" className={secondaryButtonClasses} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

export function CredentialsPage() {
  const { data: credentials, isLoading } = useCredentials()
  const deleteCredential = useDeleteCredential()
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'list' | 'add' | { edit: Credential }>('list')

  async function handleDelete(id: number, label: string) {
    if (!window.confirm(`Delete the credential "${label}"? This cannot be undone.`)) return
    setError(null)
    try {
      await deleteCredential.mutateAsync(id)
    } catch (err) {
      // A credential still in use comes back as a 409 naming exactly what's using it (an integration,
      // a network auto-login binding, or the chat assistant) - show that, not a generic failure.
      setError(err instanceof ApiError ? err.message : 'Failed to delete credential.')
    }
  }

  return (
    <div>
      {mode === 'list' ? (
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-fg-muted">
            Every stored credential, whether or not an integration uses it. Secrets are encrypted and never shown.
          </p>
          <button type="button" className={`${primaryButtonClasses} shrink-0`} onClick={() => setMode('add')}>
            New credential
          </button>
        </div>
      ) : mode === 'add' ? (
        <AddCredentialForm onDone={() => setMode('list')} />
      ) : (
        <EditCredentialForm key={mode.edit.id} credential={mode.edit} onDone={() => setMode('list')} />
      )}

      {error && (
        <p className="mt-4 rounded-control border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mt-4">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-left text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Label</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Used by</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
                <th className="px-4 py-2.5 font-medium">Last used</th>
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
              {credentials?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={6}>
                    No credentials saved yet.
                  </td>
                </tr>
              )}
              {credentials?.map((credential) => (
                <tr key={credential.id} className="border-b border-line align-middle last:border-b-0">
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">{credential.label}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <Badge tone="neutral">{credential.credential_type}</Badge>
                    {credential.in_agent_pool && (
                      <span className="ml-1.5" title="Agents set to use the pool may try this credential on hosts without an integration.">
                        <Badge tone="info">In agent pool</Badge>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {credential.used_by.length === 0 ? (
                      <Badge tone="neutral">Unused - safe to delete</Badge>
                    ) : (
                      <span className="text-xs text-fg-muted">{credential.used_by.join(', ')}</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{formatDate(credential.created_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{formatDate(credential.last_used_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <button
                      type="button"
                      className="mr-4 inline-flex items-center gap-1 text-xs font-medium text-accent-strong hover:underline"
                      title="Rename this credential or replace its secret."
                      onClick={() => setMode({ edit: credential })}
                    >
                      <EditIcon />
                      Edit
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline disabled:opacity-50"
                      title="Delete this credential. Refused if anything in the Used by column still references it."
                      disabled={deleteCredential.isPending}
                      onClick={() => handleDelete(credential.id, credential.label)}
                    >
                      <DeleteIcon />
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
