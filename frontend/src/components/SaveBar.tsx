import type { ReactNode } from 'react'

interface SaveBarProps {
  title?: ReactNode
  description?: ReactNode
  /** Mutation state, so the user sees the save happen. */
  saving: boolean
  saved?: boolean
  error?: string | null
  label?: string
  onCancel?: () => void
  /** For a bar rendered outside its <form>: the form's id. */
  form?: string
}

/**
 * The header row of every settings form: what it is on the left, Save on the top right.
 * Render it as the first child of the <form> (or point `form` at the form's id) so Save is a real
 * submit button, which also makes Enter in a field save.
 */
export function SaveBar({ title, description, saving, saved, error, label = 'Save', onCancel, form }: SaveBarProps) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 pt-1.5">{title && <div className="text-sm font-medium text-fg">{title}</div>}</div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span role="status" className="text-xs text-fg-muted">
            {saving ? 'Saving…' : error ? <span className="text-red-600 dark:text-red-400">{error}</span> : saved ? 'Saved.' : ''}
          </span>
          {onCancel && (
            <button
              type="button"
              form={form}
              className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10"
              onClick={onCancel}
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            form={form}
            disabled={saving}
            className="rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50"
          >
            {label}
          </button>
        </div>
      </div>
      {description && <p className="mt-1 text-xs text-fg-muted">{description}</p>}
    </div>
  )
}
