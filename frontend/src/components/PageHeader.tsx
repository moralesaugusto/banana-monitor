import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
}

/** The title row every page starts with: the page name as the active underlined tab, actions on the right. */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div>
      <div className="flex items-end justify-between gap-4 border-b border-line">
        <h1 className="-mb-px border-b-2 border-accent px-0.5 pb-2 text-lg font-medium tracking-tight text-accent-strong">
          {title}
        </h1>
        {actions && <div className="flex shrink-0 items-center gap-2 pb-1.5">{actions}</div>}
      </div>
      {description && <p className="mt-3 max-w-2xl text-sm text-fg-muted">{description}</p>}
    </div>
  )
}
