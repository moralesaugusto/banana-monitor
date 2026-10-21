import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { ChatPanel } from './ChatPanel'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

function savedCollapsed(): boolean {
  try {
    return localStorage.getItem('banana-sidebar') === 'collapsed'
  } catch {
    return false
  }
}

/** Top bar across the full width, a collapsible sidebar on the left, the page on the right. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(savedCollapsed)

  function toggleCollapsed() {
    setCollapsed((value) => {
      try {
        localStorage.setItem('banana-sidebar', value ? 'expanded' : 'collapsed')
      } catch {
        // not persisted
      }
      return !value
    })
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface text-fg">
      <TopBar onMenu={() => setMenuOpen(true)} />
      {menuOpen && (
        <div className="fixed inset-0 top-14 z-30 bg-black/40 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden />
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          collapsed={collapsed}
          onToggleCollapsed={toggleCollapsed}
          mobileOpen={menuOpen}
          onNavigate={() => setMenuOpen(false)}
        />
        <main className="min-w-0 flex-1 overflow-x-clip p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <ChatPanel />
    </div>
  )
}
