const base = 'http://127.0.0.1:8787'

export async function opayai<T>(path: string, body: Record<string, string> = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || 'opayai request failed')
  return result
}
