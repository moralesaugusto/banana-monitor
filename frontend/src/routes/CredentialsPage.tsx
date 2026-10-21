import { useState } from 'react'
import { ApiError } from '../api/client'
import { useCredentials, useDeleteCredential } from '../api/credentials'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'
import { DeleteIcon } from '../components/icons'

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

export function CredentialsPage() {
  const { data: credentials, isLoading } = useCredentials()
  const deleteCredential = useDeleteCredential()
  const [error, setError] = useState<string | null>(null)

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
      <PageHeader
        title="Credentials"
        description="Every stored credential, independent of which integration (if any) uses it. Create one from the Integrations page's '+ New credential' flow — this page is for reviewing and deleting them."
      />

      {error && (
        <p className="mt-4 rounded-control border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mt-6">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-left text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Label</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
                <th className="px-4 py-2.5 font-medium">Last used</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                    Loading…
                  </td>
                </tr>
              )}
              {credentials?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                    No credentials saved yet.
                  </td>
                </tr>
              )}
              {credentials?.map((credential) => (
                <tr key={credential.id} className="border-b border-line align-middle last:border-b-0">
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">{credential.label}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <Badge tone="neutral">{credential.credential_type}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{formatDate(credential.created_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-fg-muted">{formatDate(credential.last_used_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline disabled:opacity-50"
                      title="Delete this credential. Refused if an integration, network auto-login binding or the chat assistant still uses it."
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
