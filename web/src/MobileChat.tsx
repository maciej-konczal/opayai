import { useState } from 'react'
import type { Intent, LedgerEvent, Offer, Purchase } from './types'

const money = (grosze: number) => new Intl.NumberFormat('pl-PL', {
  style: 'currency', currency: 'PLN', maximumFractionDigits: 2,
}).format(grosze / 100)

const deliveryLabel = (method: string) => method === 'paczkomat' ? 'parcel locker' : method
const statusLabel: Record<string, string> = {
  paid: 'Payment confirmed', shipped: 'On the way', in_paczkomat: 'Ready for pickup',
  picked_up: 'Picked up', return_requested: 'Return approved', return_in_transit: 'Return in transit',
}

type Props = {
  prompt: string
  setPrompt: (value: string) => void
  notice: string
  intent: Intent | null
  offers: Offer[]
  filtered: {offer: Offer; violated_clause: string}[]
  purchase: Purchase | null
  events: LedgerEvent[]
  payUrl: string | null
  demo: boolean
  onDraft: () => Promise<void>
  onSign: (id: string, type: 'intent' | 'cart' | 'resolution') => Promise<void>
  onBuy: (offer: Offer) => Promise<void>
  onStartBlik: () => Promise<void>
  onConfirmBlik: (code: string) => Promise<void>
  onRetryBlik: () => Promise<void>
  onAdvance: () => Promise<void>
  onKeep: () => Promise<void>
  onReturn: () => Promise<void>
  onEvidence: () => Promise<void>
  onRevoke: () => Promise<void>
  onFault: (type: 'wrong_item' | 'decline_payment') => Promise<void>
}

function proposalTotal(purchase: Purchase) {
  const totals = purchase.proposal.totals as {total?: number} | undefined
  return totals?.total ?? purchase.cart?.totals.total ?? 0
}

export function MobileChat(props: Props) {
  const [blikOpen, setBlikOpen] = useState(false)
  const [blikCode, setBlikCode] = useState('')
  const [paying, setPaying] = useState(false)
  const {intent, purchase} = props
  const canAdvance = Boolean(purchase?.order?.id) && [
    'paid', 'shipped', 'in_paczkomat', 'return_requested', 'return_in_transit',
  ].includes(purchase!.order_status)
  const isClosed = purchase?.order_status === 'closed_accepted' || purchase?.order_status === 'closed_refunded'

  async function openBlik() {
    await props.onStartBlik()
    setBlikOpen(true)
  }

  async function confirmBlik() {
    if (!/^\d{6}$/.test(blikCode)) return
    setPaying(true)
    try {
      await props.onConfirmBlik(blikCode)
      setBlikOpen(false)
      setBlikCode('')
    } finally {
      setPaying(false)
    }
  }

  async function retryBlik() {
    await props.onRetryBlik()
    setBlikOpen(true)
  }

  return <section className="mobile-chat" aria-label="OPayAI mobile agent conversation">
    <header className="mobile-header">
      <div className="mobile-agent-mark">O</div>
      <div><b>OPayAI</b><small><i/> working in the background</small></div>
      {intent?.status === 'open' ? <button onClick={props.onRevoke}>Revoke</button> : <span className="mobile-secure">Human in control</span>}
    </header>

    <div className="mobile-thread">
      {!intent ? <article className="agent-message welcome-message">
        <span className="agent-avatar">O</span>
        <div><small>Your purchasing agent</small><h1>What can I buy for you?</h1><p>I’ll find the product, verify the terms, and only come back for decisions that require you.</p></div>
      </article> : null}

      {intent ? <article className="user-message"><span>🎤</span><p>{intent.description}</p></article> : null}

      {intent ? <article className="agent-message">
        <span className="agent-avatar">O</span>
        <div className="chat-card mandate-chat-card">
          <small>PURCHASE MANDATE</small>
          <h2>{money(intent.constraints.max_total)} max.</h2>
          <div className="chat-chips"><span>{intent.constraints.categories.join(', ')}</span><span>minimum {intent.constraints.min_return_window_days}-day returns</span><span>BLIK</span></div>
          {intent.status === 'draft' ? <><p>These are the exact boundaries I will follow. Your signature only authorizes these terms.</p><button className="mobile-primary" onClick={() => props.onSign(intent.id, 'intent')}>Approve mandate</button></> : <div className="verified-line">✓ Signed on this device</div>}
        </div>
      </article> : null}

      {intent?.status === 'open' && !purchase ? <article className="agent-message">
        <span className="agent-avatar">O</span>
        <div><p>I checked availability, delivery, and return terms. These offers fit your mandate:</p>
          <div className="mobile-offers">{props.offers.map(offer => <button className="mobile-offer" key={offer.sku} onClick={() => props.onBuy(offer)}>
            <span><b>{offer.title}</b><small>{deliveryLabel(offer.delivery_method)} · {offer.return_policy.window_days}-day returns</small></span><strong>{money(offer.price)}</strong><i>Choose</i>
          </button>)}</div>
          {props.filtered.length ? <details className="mobile-filtered"><summary>{props.filtered.length} offers blocked by your policy</summary>{props.filtered.map(item => <p key={item.offer.sku}>{item.offer.title}<code>{item.violated_clause}</code></p>)}</details> : null}
        </div>
      </article> : null}

      {purchase ? <article className="agent-message">
        <span className="agent-avatar">O</span>
        <div className="chat-card checkout-chat-card">
          <small>PURCHASE PROPOSAL</small>
          <h2>{String(purchase.proposal.sku ?? 'Selected product')}</h2>
          <div className="checkout-total"><span>Total</span><strong>{money(proposalTotal(purchase))}</strong></div>
          <p>Delivery: {deliveryLabel(String(purchase.proposal.delivery_method ?? 'paczkomat'))} · promised by {String(purchase.proposal.delivery_promise ?? '')}</p>
          {purchase.status === 'awaiting_human_authorization' ? <button className="mobile-primary" onClick={() => props.onSign(purchase.id, 'cart')}>Approve this exact cart</button> : null}
          {purchase.status === 'cart_signed' ? <><div className="verified-line">✓ Product and price signed</div><button className="blik-button" onClick={openBlik}><span>BLIK</span> Pay in chat</button></> : null}
          {purchase.order_status === 'payment_pending' ? <button className="blik-button" onClick={() => setBlikOpen(true)}><span>BLIK</span> Enter code and confirm</button> : null}
          {props.demo && purchase.order_status === 'payment_pending' ? <button className="mobile-demo" onClick={() => props.onFault('decline_payment')}>Demo · decline first BLIK attempt</button> : null}
          {purchase.order_status === 'payment_failed' ? <button className="mobile-danger" onClick={retryBlik}>Payment declined · try again</button> : null}
        </div>
      </article> : null}

      {purchase && ['paid', 'shipped', 'in_paczkomat', 'picked_up', 'return_requested', 'return_in_transit'].includes(purchase.order_status) ? <article className="agent-message">
        <span className="agent-avatar">O</span>
        <div className="chat-card status-chat-card">
          <small>ORDER STATUS</small>
          <h2>{statusLabel[purchase.order_status] ?? purchase.order_status.replaceAll('_', ' ')}</h2>
          {purchase.order_status === 'paid' ? <p>Payment confirmed. The store is preparing your order.</p> : null}
          {purchase.order_status === 'shipped' ? <p>Your parcel is on the way. I’ll keep tracking it in the background.</p> : null}
          {purchase.order_status === 'in_paczkomat' ? <div className="locker-code"><span>Parcel locker WAW117M</span><b>482 913</b><small>Pickup code</small></div> : null}
          {purchase.order_status === 'picked_up' && !purchase.exception ? <><p>The item was collected and matches your signed cart. What would you like to do?</p><div className="decision-row"><button className="mobile-primary" onClick={props.onKeep}>Keep it</button><button className="mobile-secondary" onClick={props.onReturn}>Return it</button></div></> : null}
          {purchase.order_status === 'return_requested' ? <p>Return approved. Shipping code: <b>OPAY-RETURN-482913</b></p> : null}
          {purchase.order_status === 'return_in_transit' ? <p>Your return is on the way. I’ll trigger the refund when it arrives.</p> : null}
          {props.demo && ['paid', 'shipped', 'in_paczkomat'].includes(purchase.order_status) ? <button className="mobile-demo" onClick={() => props.onFault('wrong_item')}>Demo · send the wrong item</button> : null}
          {props.demo && canAdvance ? <button className="mobile-demo" onClick={props.onAdvance}>Demo · next stage →</button> : null}
        </div>
      </article> : null}

      {purchase?.exception ? <article className="agent-message">
        <span className="agent-avatar alert-avatar">!</span>
        <div className="chat-card exception-chat-card"><small>{purchase.exception.type === 'ITEM_MISMATCH' ? 'MISMATCH DETECTED' : 'RETURN DECISION'}</small><h2>{purchase.exception.type === 'ITEM_MISMATCH' ? 'Wrong item' : 'Full return'}</h2><p>{purchase.exception.type === 'ITEM_MISMATCH' ? 'The item you received does not match the cart you signed.' : 'You requested a return. This exact resolution still needs your signature.'}</p><div className="mobile-diff"><div><small>EXPECTED</small><pre>{JSON.stringify(purchase.exception.evidence.expected, null, 2)}</pre></div><div><small>RECEIVED</small><pre>{JSON.stringify(purchase.exception.evidence.observed, null, 2)}</pre></div></div>{purchase.exception.resolution_status === 'proposed' ? <button className="mobile-danger" onClick={() => props.onSign(purchase.id, 'resolution')}>Approve full return</button> : <div className="verified-line">✓ Return approved</div>}</div>
      </article> : null}

      {isClosed ? <article className="agent-message">
        <span className="agent-avatar">O</span>
        <div className="chat-card closed-chat-card"><small>CLOSED</small><h2>{purchase?.order_status === 'closed_refunded' ? 'Refund complete' : 'Purchase complete'}</h2><p>The full history, policy decisions, and signatures are ready as evidence.</p><button className="mobile-secondary" onClick={props.onEvidence}>Download evidence bundle</button></div>
      </article> : null}

      {props.events.length ? <details className="mobile-audit"><summary>Full activity ledger · {props.events.length}</summary>{props.events.map(event => <div key={event.seq}><span>{event.actor}</span><b>{event.type.replaceAll('_', ' ')}</b><time>{new Date(event.ts).toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'})}</time></div>)}</details> : null}
      <p className="mobile-notice">{props.notice}</p>
    </div>

    {!intent ? <footer className="mobile-composer"><button className="voice-button" aria-label="Record a message">●</button><textarea aria-label="Describe what you need" value={props.prompt} onChange={event => props.setPrompt(event.target.value)}/><button className="send-button" aria-label="Send purchase request" onClick={props.onDraft}>↑</button></footer> : null}

    {blikOpen ? <div className="mobile-sheet-backdrop" role="dialog" aria-modal="true" aria-label="BLIK payment prompt"><div className="mobile-blik-sheet">
      <div className="sheet-handle"/><small>SECURE PAYMENT · DEMO STORE</small><h2>{money(purchase ? proposalTotal(purchase) : 0)}</h2><p>Enter your six-digit BLIK code. OPayAI cannot see or approve this decision.</p>
      <input value={blikCode} onChange={event => setBlikCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="000 000" aria-label="Six-digit BLIK code"/>
      <button className="blik-confirm" disabled={blikCode.length !== 6 || paying} onClick={confirmBlik}>{paying ? 'Confirming…' : 'Confirm in bank (demo)'}</button>
      {props.payUrl ? <a href={props.payUrl} target="_blank" rel="noreferrer">Open separate bank screen</a> : null}
      <button className="cancel-payment" onClick={() => setBlikOpen(false)}>Cancel</button>
    </div></div> : null}
  </section>
}
