import type { CredentialType } from '../api/credentials'
import type { IntegrationTypeInfo } from '../api/integrations'

/** The credential shape each built-in plugin's credential_schema actually asks for - used to pick a
 * sensible credential_type without making the user choose one that duplicates the integration Type
 * they already picked. Falls back to api_token for an unknown future plugin. */
export const CREDENTIAL_TYPE_FOR_INTEGRATION: Record<string, CredentialType> = {
  generic_ssh: 'ssh_key',
  proxmox: 'api_token',
  adguard_home: 'basic_auth',
  homebridge: 'basic_auth',
  omada: 'basic_auth',
  windows_winrm: 'basic_auth',
  virustotal: 'api_token',
}

/** generic_ssh takes either a private key or a password (see SshCredential on the backend) - label the
 * saved credential by whichever one was actually filled in, instead of a fixed guess. */
export function credentialTypeFor(typeKey: string, secret?: Record<string, unknown>): CredentialType {
  if (typeKey === 'generic_ssh' && secret && !secret.private_key && secret.password) return 'ssh_password'
  return CREDENTIAL_TYPE_FOR_INTEGRATION[typeKey] ?? 'api_token'
}

/** Integration types that take a credential, i.e. the layouts a secret can be entered in. */
export function typesWithCredentials(types: IntegrationTypeInfo[] | undefined): IntegrationTypeInfo[] {
  return (types ?? []).filter((t) => t.credential_schema)
}

/** The integration type whose secret layout most likely matches a stored credential of this type. */
export function defaultTypeForCredential(types: IntegrationTypeInfo[] | undefined, credentialType: CredentialType): string {
  const candidates = typesWithCredentials(types)
  const match = candidates.find(
    (t) => CREDENTIAL_TYPE_FOR_INTEGRATION[t.type_key] === credentialType || (credentialType === 'ssh_password' && t.type_key === 'generic_ssh'),
  )
  return match?.type_key ?? ''
}
