import { useApproveSshHostKey, useForgetSshHostKey, useSshHostKeys } from '../api/sshHostKeys'
import { Card } from './Card'

const linkButton = 'text-xs font-medium text-accent-strong hover:underline disabled:opacity-50'

/** SSH host keys auto-login has seen. A new or changed key must be approved before any password is tried on that host. */
export function SshHostKeysCard() {
  const { data: keys } = useSshHostKeys()
  const approve = useApproveSshHostKey()
  const forget = useForgetSshHostKey()
  if (!keys || keys.length === 0) return null

  return (
    <Card className="mt-6 overflow-x-auto">
      <div className="px-4 pt-3 text-sm font-medium text-fg">SSH host keys</div>
      <p className="px-4 pb-2 text-xs text-fg-muted">
        Auto-login sends no password to a host until you approve the key it presents. Check the fingerprint against the
        host (<code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code>) before approving.
      </p>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-fg-muted">
            <th className="px-4 py-2 font-medium">Host</th>
            <th className="px-4 py-2 font-medium">Fingerprint</th>
            <th className="px-4 py-2 font-medium">State</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key.id} className="border-b border-line last:border-b-0">
              <td className="px-4 py-2 font-mono text-xs">
                {key.host}:{key.port}
              </td>
              <td className="px-4 py-2 font-mono text-xs text-fg-muted">{key.fingerprint}</td>
              <td className="px-4 py-2 text-xs">
                {key.approved ? 'approved' : key.changed ? 'key changed, needs approval' : 'needs approval'}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right">
                <span className="flex justify-end gap-3">
                  {!key.approved && (
                    <button type="button" className={linkButton} disabled={approve.isPending} onClick={() => approve.mutate(key.id)}>
                      Approve
                    </button>
                  )}
                  <button type="button" className="text-xs font-medium text-red-600 hover:underline" onClick={() => forget.mutate(key.id)}>
                    Forget
                  </button>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}
