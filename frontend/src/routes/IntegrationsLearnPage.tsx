import { Link } from 'react-router-dom'
import { useIntegrationTypes } from '../api/integrations'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

/** Plain-language "what it watches / what it needs" per built-in plugin, keyed by type_key. Rewritten
 * for an end user from each plugin's own docstring and docs/integrations.md - not copy-pasted, those are
 * written for developers. Falls back to the plugin's own display_name/no-credential note for anything
 * registered that isn't listed here, so a future plugin never renders a blank card. */
const PLUGIN_GUIDE: Record<string, string> = {
  http_tcp: 'Checks that a URL or TCP port responds. No login needed - just a host, port or URL.',
  generic_ssh:
    'Reads load, memory and disk usage over SSH, using a fixed set of read-only commands - it never ' +
    'runs anything you (or the AI agents) type. Detects the host\'s OS once (uname) and uses the ' +
    'matching command set - Linux is the only one implemented today. Needs an SSH username and ' +
    'private key for a dedicated, least-privilege account. The host\'s SSH key is pinned on first ' +
    'connection.',
  proxmox:
    'Finds every node, VM and LXC on a Proxmox VE server and polls their CPU, memory and uptime. Needs ' +
    "a Proxmox API token (its id and secret) - use the built-in read-only PVEAuditor role, not a full " +
    'admin token.',
  dns: 'Resolves a DNS query against a resolver to confirm it answers. No login needed.',
  dhcp: 'A best-effort check that a DHCP server replies to a discover packet. No login needed - see the ' +
    'Known limitation note in the documentation for why this signal is weaker than the other checks.',
  adguard_home:
    'Reads query/blocking counts and protection state from AdGuard Home. Needs its web UI username and ' +
    'password.',
  homebridge: 'Reads accessory count and host metrics from the Homebridge UI. Needs its UI login.',
  omada: "Reads client and device counts from a TP-Link Omada controller. Needs its controller login.",
  windows_winrm:
    'Reads CPU, memory and disk usage from a Windows host over WinRM (HTTPS only), using one fixed ' +
    'read-only script. Needs a non-administrator Windows account in the Remote Management Users group.',
  virustotal:
    "Doesn't monitor anything on its own - it stores a VirusTotal API key so the AI agents' lookup tool " +
    'can check a hash, IP or domain. Rate-limited to the free tier by default.',
}

const WALLET_POINTS: { title: string; body: string }[] = [
  {
    title: 'What it is',
    body:
      'A credential saved with no Host (and, for Linux/SSH and Windows, no Device either) on the ' +
      'Integrations page. Instead of one credential tied to one host you already know about, a wallet ' +
      'credential is tried against whatever host discovery finds that looks like a match.',
  },
  {
    title: 'How a match happens',
    body:
      'Every network scan guesses what each open port is running (the same "Looks like" hint shown on ' +
      'the Discovery page). For every wallet credential of a matching type, the app tries it against ' +
      'that host. The first one that authenticates auto-creates a real, host-bound integration - no ' +
      'manual "configure as" step.',
  },
  {
    title: 'Which plugins support it',
    body:
      'All six credentialed plugins: Generic (SSH), Proxmox, AdGuard Home, Homebridge, Omada and Windows ' +
      '(WinRM). The three that only take an API key or have nothing to connect to (generic HTTP/TCP, ' +
      'DNS, DHCP, VirusTotal) have no host concept, so there is nothing to leave empty.',
  },
  {
    title: 'The trust trade-off',
    body:
      'This is credential spraying against your own LAN - trying a stored credential against a host it ' +
      "has not already been told accepts it. Linux/SSH still gates this on the host-key approval/pinning " +
      "setting, so a secret is never sent to an unapproved host. The other five plugins have no " +
      'equivalent concept yet, so their probe does not verify TLS (there is no certificate pinned for a ' +
      'host that has not been configured). Reasonable on a trusted single-admin home LAN; not something ' +
      "to turn on for a shared or untrusted network.",
  },
  {
    title: 'Pausing or removing one',
    body:
      'A wallet entry is an Integration like any other: disable it to stop it being tried without ' +
      'deleting the credential, or delete the integration and the credential separately from the ' +
      'Credentials page.',
  },
]

export function IntegrationsLearnPage() {
  const { data: types } = useIntegrationTypes()

  return (
    <div>
      <PageHeader
        title="How integrations work"
        description="What each integration type monitors and what it needs, plus how the credential wallet lets you save a credential before you know which host it belongs to."
      />

      <h2 className="mt-6 text-lg font-semibold">Integration types</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {(types ?? []).map((t) => (
          <Card key={t.type_key} className="p-4">
            <div className="text-sm font-semibold text-fg">{t.display_name}</div>
            <p className="mt-2 text-sm text-fg-muted">
              {PLUGIN_GUIDE[t.type_key] ?? (t.credential_schema ? 'Needs a credential.' : 'No credential needed.')}
            </p>
          </Card>
        ))}
      </div>

      <h2 className="mt-8 text-lg font-semibold">The credential wallet</h2>
      <p className="mt-2 max-w-3xl text-sm text-fg-muted">
        Set up on the <Link className="text-accent-strong hover:underline" to="/integrations">Integrations</Link>{' '}
        page by leaving Host empty when saving a credential. Review and delete saved credentials on the{' '}
        <Link className="text-accent-strong hover:underline" to="/integrations/credentials">Credentials</Link>{' '}
        page.
      </p>
      <div className="mt-3 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {WALLET_POINTS.map((p) => (
          <Card key={p.title} className="p-4">
            <div className="text-sm font-semibold text-fg">{p.title}</div>
            <p className="mt-2 text-sm text-fg-muted">{p.body}</p>
          </Card>
        ))}
      </div>
    </div>
  )
}
