export type AgentResult = { name: string, output: Record<string, unknown> }

export async function askAgent(message: string): Promise<{ text: string, results: AgentResult[] }> {
  const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error || 'Boski could not complete that request')
  return payload
}
