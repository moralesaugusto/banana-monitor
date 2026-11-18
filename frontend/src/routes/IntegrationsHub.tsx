import { Link, NavLink, Outlet } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'

const tabClasses = ({ isActive }: { isActive: boolean }) =>
  `-mb-px border-b-2 px-1 pb-2 text-sm ${
    isActive ? 'border-accent font-medium text-fg' : 'border-transparent text-fg-muted hover:text-fg'
  }`

/** One home for everything integration-related: the integrations themselves and the credentials they use. */
export function IntegrationsHub() {
  return (
    <div>
      <PageHeader
        title="Credentials & Keys"
        description={
          <>
            Connections to the systems Banana monitors, and the stored credentials they use.{' '}
            <Link to="/integrations/learn" className="text-fg underline underline-offset-2 hover:text-fg-muted">
              How it works
            </Link>
          </>
        }
      />
      <nav aria-label="Integrations sections" className="mt-4 flex gap-5 border-b border-line">
        <NavLink to="/integrations" end className={tabClasses}>
          Integrations
        </NavLink>
        <NavLink to="/integrations/credentials" className={tabClasses}>
          Credentials
        </NavLink>
      </nav>
      <div className="mt-4">
        <Outlet />
      </div>
    </div>
  )
}
