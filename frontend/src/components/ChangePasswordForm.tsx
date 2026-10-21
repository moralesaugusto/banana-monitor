import { useState } from 'react'
import { errorDetail, useChangePassword } from '../api/auth'

const inputClasses =
  'mt-1 w-full rounded-control border border-line bg-surface px-2 py-1.5 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const buttonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

/** There are no complexity rules: any non-empty password is accepted. */
export function ChangePasswordForm({ onDone }: { onDone?: () => void }) {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const mismatch = confirm !== '' && next !== confirm

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!next || next !== confirm) return
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent('')
          setNext('')
          setConfirm('')
          onDone?.()
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="text-sm">
        Current password
        <input
          type="password"
          autoComplete="current-password"
          className={inputClasses}
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </label>
      <label className="text-sm">
        New password
        <input
          type="password"
          autoComplete="new-password"
          className={inputClasses}
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
      </label>
      <label className="text-sm">
        Repeat new password
        <input
          type="password"
          autoComplete="new-password"
          className={inputClasses}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </label>
      {mismatch && <p className="text-xs text-red-600 dark:text-red-400">The passwords do not match.</p>}
      {change.error && <p className="text-xs text-red-600 dark:text-red-400">{errorDetail(change.error)}</p>}
      {change.isSuccess && <p className="text-xs text-fg-muted">Password changed.</p>}
      <div>
        <button type="submit" className={buttonClasses} disabled={change.isPending || !current || !next || mismatch}>
          {change.isPending ? 'Saving…' : 'Change password'}
        </button>
      </div>
    </form>
  )
}
