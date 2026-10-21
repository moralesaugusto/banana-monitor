import { useState, type ReactNode } from 'react'
import { errorDetail, useLogin, useMe } from '../api/auth'
import { BananaLogo } from './BananaLogo'
import { LockIcon, UserIcon } from './icons'
import { ChangePasswordForm } from './ChangePasswordForm'

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-surface text-fg">
      <header
        className="flex h-14 shrink-0 items-center px-4 text-topbar-fg"
        style={{ backgroundImage: 'linear-gradient(90deg, var(--topbar-from), var(--topbar-to))' }}
      >
        <BananaLogo />
        <span className="ml-1.5 text-[15px] font-semibold tracking-tight">Banana</span>
      </header>
      <main className="flex flex-1 justify-center px-4 pt-20">
        <div className="w-full max-w-xs">{children}</div>
      </main>
      <footer className="pb-8 text-center text-xs text-fg-subtle">Banana, a self-hosted monitor for your LAN</footer>
    </div>
  )
}

function IconField({
  icon,
  children,
}: {
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex items-center rounded-control bg-canvas focus-within:ring-1 focus-within:ring-accent">
      <span className="flex h-10 w-10 items-center justify-center border-r border-line text-fg-subtle">{icon}</span>
      {children}
    </div>
  )
}

const fieldClasses =
  'h-10 min-w-0 flex-1 bg-transparent px-3 text-sm text-fg placeholder:text-fg-subtle focus:outline-none'

function LoginForm() {
  const login = useLogin()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')

  return (
    <Centered>
      <form
        className="flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault()
          login.mutate({ username, password })
        }}
      >
        <h1 className="text-center text-xl font-medium">Sign in to Banana</h1>
        <label className="sr-only" htmlFor="login-username">
          Username
        </label>
        <IconField icon={<UserIcon className="h-5 w-5" />}>
          <input
            id="login-username"
            className={fieldClasses}
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </IconField>
        <label className="sr-only" htmlFor="login-password">
          Password
        </label>
        <IconField icon={<LockIcon className="h-5 w-5" />}>
          <input
            id="login-password"
            type="password"
            className={fieldClasses}
            placeholder="Password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </IconField>
        {login.error && <p className="text-xs text-red-600 dark:text-red-400">{errorDetail(login.error)}</p>}
        <button
          type="submit"
          disabled={login.isPending || !username || !password}
          className="h-10 rounded-control bg-accent text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50"
        >
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </Centered>
  )
}

/** Shows the app only to a signed-in user who has already replaced the default password. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { data: me, isLoading, isError } = useMe()

  if (isLoading) return <Centered><p className="text-sm text-fg-muted">Loading…</p></Centered>
  if (isError) return <Centered><p className="text-sm text-red-600">Cannot reach the server.</p></Centered>
  if (!me) return <LoginForm />
  if (me.must_change_password) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold">Choose a new password</h1>
        <p className="mb-4 mt-1 text-sm text-fg-muted">
          You signed in with the default password. Set your own before continuing; any password is accepted.
        </p>
        <ChangePasswordForm />
      </Centered>
    )
  }
  return <>{children}</>
}
