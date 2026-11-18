import { type Credential, useCredentials } from '../../api/credentials'

const NEW_KEY = ''

/** An `api_token` credential that is free to be used as an LLM key: not one that Telegram or an
 * integration (Proxmox, VirusTotal, ...) already owns. Decided by what uses it, not by its label -
 * a key saved as "Artex" used to be created fine and then vanish from every list because its label
 * lacked "OpenRouter". */
export function isStandaloneApiKey(credential: Credential): boolean {
  return (
    credential.credential_type === 'api_token' &&
    !credential.used_by.some((user) => user === 'Telegram' || user.startsWith('integration '))
  )
}

/**
 * Replaces a plain "paste your API key" input with a choice: reuse an `api_token` credential
 * already saved from somewhere else in the app, or paste a new one. Without this, every form that
 * needs an API key could only mint a brand new credential - there was no way to point at one
 * you'd already stored, and no visible list of what's actually on file (see docs/decisions.md for
 * the incident this fixes). `matchLabel`, when given, narrows the dropdown to credentials whose label contains
 * that text (case-insensitive) instead - the knowledge base's embedding-host credential passes "".
 */
export function OpenRouterKeyPicker({
  inputClasses,
  credentialId,
  onSelectCredential,
  apiKey,
  onChangeApiKey,
  matchLabel,
  ariaLabel = 'Stored OpenRouter key',
}: {
  inputClasses: string
  credentialId: number | null
  onSelectCredential: (id: number | null) => void
  apiKey: string
  onChangeApiKey: (value: string) => void
  matchLabel?: string
  ariaLabel?: string
}) {
  const { data: credentials } = useCredentials()
  // The saved selection is always listed: if it were filtered out, the dropdown and the new-key input
  // would both disappear and the field would show nothing at all.
  const stored = (credentials ?? []).filter((c) =>
    c.id === credentialId ||
    (matchLabel === undefined
      ? isStandaloneApiKey(c)
      : c.credential_type === 'api_token' && c.label.toLowerCase().includes(matchLabel.toLowerCase())),
  )
  const selected = credentialId !== null ? String(credentialId) : NEW_KEY

  function handleSelect(value: string) {
    if (value === NEW_KEY) {
      onSelectCredential(null)
    } else {
      onSelectCredential(Number(value))
      onChangeApiKey('')
    }
  }

  return (
    <>
      {stored.length > 0 && (
        <select
          aria-label={ariaLabel}
          className={inputClasses}
          value={selected}
          onChange={(e) => handleSelect(e.target.value)}
        >
          <option value={NEW_KEY}>Enter a new key below...</option>
          {stored.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      )}
      {selected === NEW_KEY && (
        <input
          type="password"
          className={inputClasses}
          value={apiKey}
          onChange={(e) => onChangeApiKey(e.target.value)}
          placeholder="sk-or-..."
        />
      )}
    </>
  )
}
