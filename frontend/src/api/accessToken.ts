const STORAGE_KEY = 'meetingmind.apiAccessToken'
export const ACCESS_TOKEN_REQUIRED_EVENT = 'meetingmind-access-token-required'

export function getAccessToken(): string {
  return sessionStorage.getItem(STORAGE_KEY)?.trim() || ''
}

export function hasAccessToken(): boolean {
  return Boolean(getAccessToken())
}

export function setAccessToken(token: string): void {
  const normalized = token.trim()
  if (normalized) sessionStorage.setItem(STORAGE_KEY, normalized)
  else sessionStorage.removeItem(STORAGE_KEY)
}

export function clearAccessToken(): void {
  sessionStorage.removeItem(STORAGE_KEY)
}

export function authorizationHeader(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function notifyAccessTokenRequired(invalid: boolean): void {
  if (invalid) clearAccessToken()
  window.dispatchEvent(new CustomEvent(ACCESS_TOKEN_REQUIRED_EVENT, { detail: { invalid } }))
}
