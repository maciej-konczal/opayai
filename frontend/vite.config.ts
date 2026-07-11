import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const tools = [
  { type: 'function', name: 'start_purchase', description: 'Create the signed purchase intent and retrieve three ranked offers for the user request.', parameters: { type: 'object', properties: {}, additionalProperties: false } },
  { type: 'function', name: 'select_offer', description: 'Create a cart and run policy checks after the user explicitly selects an offer.', parameters: { type: 'object', properties: { intent_id: { type: 'string' }, offer_id: { type: 'string' } }, required: ['intent_id', 'offer_id'], additionalProperties: false } },
  { type: 'function', name: 'approve_purchase', description: 'Record the user approval for the precise cart.', parameters: { type: 'object', properties: { cart_id: { type: 'string' } }, required: ['cart_id'], additionalProperties: false } },
  { type: 'function', name: 'complete_passkey_and_pay', description: 'Run passkey step-up then settle the approved payment.', parameters: { type: 'object', properties: { cart_id: { type: 'string' } }, required: ['cart_id'], additionalProperties: false } },
  { type: 'function', name: 'deliver_order', description: 'Advance a paid order through shipping to delivered.', parameters: { type: 'object', properties: { order_id: { type: 'string' } }, required: ['order_id'], additionalProperties: false } },
  { type: 'function', name: 'return_order', description: 'Request a return for a delivered order after the user asks to return it.', parameters: { type: 'object', properties: { order_id: { type: 'string' } }, required: ['order_id'], additionalProperties: false } },
]

const bridge: Record<string, string[]> = {
  start_purchase: ['/checkout/start'], select_offer: ['/checkout/select'], approve_purchase: ['/checkout/approve'],
  complete_passkey_and_pay: ['/checkout/passkey', '/checkout/pay'], deliver_order: ['/order/advance', '/order/advance'], return_order: ['/order/return'],
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return { plugins: [react(), {
    name: 'opayai-agent',
    configureServer(server) { server.middlewares.use('/api/chat', async (req, res) => {
      if (req.method !== 'POST') { res.statusCode = 405; return res.end() }
      let raw = ''; for await (const chunk of req) raw += chunk
      try {
        const { message } = JSON.parse(raw)
        const callBridge = async (name: string, args: Record<string, string>) => {
          let result: unknown
          for (const path of bridge[name] || []) {
            const payload = name === 'complete_passkey_and_pay' || name === 'deliver_order' ? { cart_id: args.cart_id, order_id: args.order_id } : args
            const response = await fetch(`http://127.0.0.1:8787${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
            result = await response.json()
            if (!response.ok) throw new Error((result as { error?: string }).error || 'purchase tool failed')
          }
          return result
        }
        const instructions = 'You are Boski, a concise commerce assistant. Use purchase tools to perform actions. Never purchase or return without the user explicitly asking. After any tool call, always give the user a short, friendly summary of what happened and the next choice they can make.'
        let response = await fetch('https://api.openai.com/v1/responses', { method: 'POST', headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ model: 'gpt-4.1-mini', instructions, input: message, tools }) }).then(r => r.json()) as any
        const results: Array<{ name: string, output: any }> = []
        for (let turn = 0; turn < 6; turn++) {
          const calls = (response.output || []).filter((item: any) => item.type === 'function_call')
          if (!calls.length) break
          const outputs = []
          for (const call of calls) { const output = await callBridge(call.name, JSON.parse(call.arguments)); results.push({ name: call.name, output }); outputs.push({ type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(output) }) }
          response = await fetch('https://api.openai.com/v1/responses', { method: 'POST', headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ model: 'gpt-4.1-mini', instructions, previous_response_id: response.id, input: outputs, tools }) }).then(r => r.json()) as any
        }
        const text = response.output_text || (response.output || []).flatMap((item: any) => item.content || []).filter((item: any) => item.type === 'output_text').map((item: any) => item.text).join('')
        res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ text, results }))
      } catch (error) { res.statusCode = 500; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ error: error instanceof Error ? error.message : 'Agent error' })) }
    }) }
  }] }
})
