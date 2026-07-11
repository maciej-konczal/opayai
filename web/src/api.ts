import type { Intent, LedgerEvent, Offer, Purchase } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {headers: {'Content-Type': 'application/json'}, ...init})
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail ?? body.violated_clause ?? 'Request failed')
  return body as T
}
export const api = {
  draft: (text: string) => request<Intent>('/api/intents/draft', {method: 'POST', body: JSON.stringify({text})}),
  signOptions: (id: string, type: 'intent' | 'cart' | 'resolution') => request('/api/webauthn/auth/options', {method: 'POST', body: JSON.stringify({context_id: id, context_type: type})}),
  verify: (id: string, type: 'intent' | 'cart' | 'resolution') => request(`/api/webauthn/auth/verify`, {method: 'POST', body: JSON.stringify({context_id: id, context_type: type, assertion: {}})}),
  products: (intentId?: string) => request<{offers: Offer[]; filtered_out: {offer: Offer; violated_clause: string}[]}>(`/api/products?intent_id=${intentId ?? ''}`),
  purchase: (intent_id: string, sku: string) => request<{purchase_id: string; status: string; proposal: Record<string, unknown>}>('/api/purchases', {method: 'POST', body: JSON.stringify({intent_id, sku, qty: 1})}),
  getPurchase: (id: string) => request<Purchase>(`/api/purchases/${id}`),
  rail: (id: string) => request<{pay_url: string}>(`/api/purchases/${id}/select-rail`, {method: 'POST', body: JSON.stringify({rail: 'blik_lite'})}),
  retry: (id: string) => request<{pay_url: string}>(`/api/purchases/${id}/retry-payment`, {method: 'POST'}),
  advance: (orderId: string) => request<Purchase>(`/api/demo/advance/${orderId}`, {method: 'POST'}),
  fault: (orderId: string, type: string) => request(`/api/demo/fault/${orderId}`, {method: 'POST', body: JSON.stringify({type})}),
  satisfied: (id: string) => request<Purchase>(`/api/purchases/${id}/confirm-satisfied`, {method: 'POST'}),
  resolution: (id: string) => request(`/api/purchases/${id}/approve-resolution`, {method: 'POST'}),
  revoke: (id: string) => request<Intent>(`/api/intents/${id}/revoke`, {method: 'POST'}),
  evidence: (id: string) => request(`/api/purchases/${id}/evidence`),
  events: (callback: (event: LedgerEvent) => void) => { const source = new EventSource(`${BASE}/api/events`); source.addEventListener('ledger', (raw) => callback(JSON.parse((raw as MessageEvent).data))); return () => source.close() },
}
