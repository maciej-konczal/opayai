import { useState } from 'react'
import type { Intent, LedgerEvent, Offer, Purchase } from './types'

const money = (grosze: number) => new Intl.NumberFormat('pl-PL', {
  style: 'currency', currency: 'PLN', maximumFractionDigits: 2,
}).format(grosze / 100)

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

  return <section className="mobile-chat" aria-label="MandateLoop mobile agent conversation">
    <header className="mobile-header">
      <div className="mobile-agent-mark">M</div>
      <div><b>MandateLoop</b><small><i/> działa w tle</small></div>
      {intent?.status === 'open' ? <button onClick={props.onRevoke}>Cofnij</button> : <span className="mobile-secure">Human in control</span>}
    </header>

    <div className="mobile-thread">
      {!intent ? <article className="agent-message welcome-message">
        <span className="agent-avatar">M</span>
        <div><small>Twój agent zakupowy</small><h1>Co mam dla Ciebie kupić?</h1><p>Znajdę produkt, sprawdzę warunki i wrócę tylko po decyzje, których nie mogę podjąć za Ciebie.</p></div>
      </article> : null}

      {intent ? <article className="user-message"><span>🎤</span><p>{intent.description}</p></article> : null}

      {intent ? <article className="agent-message">
        <span className="agent-avatar">M</span>
        <div className="chat-card mandate-chat-card">
          <small>MANDAT ZAKUPOWY</small>
          <h2>{money(intent.constraints.max_total)} maks.</h2>
          <div className="chat-chips"><span>{intent.constraints.categories.join(', ')}</span><span>zwrot min. {intent.constraints.min_return_window_days} dni</span><span>BLIK</span></div>
          {intent.status === 'draft' ? <><p>To są dokładne granice działania. Podpis wiąże tylko te warunki.</p><button className="mobile-primary" onClick={() => props.onSign(intent.id, 'intent')}>Zatwierdź mandat</button></> : <div className="verified-line">✓ Podpisany na tym urządzeniu</div>}
        </div>
      </article> : null}

      {intent?.status === 'open' && !purchase ? <article className="agent-message">
        <span className="agent-avatar">M</span>
        <div><p>Sprawdziłem dostępność, dostawę i zasady zwrotu. Te oferty mieszczą się w mandacie:</p>
          <div className="mobile-offers">{props.offers.map(offer => <button className="mobile-offer" key={offer.sku} onClick={() => props.onBuy(offer)}>
            <span><b>{offer.title}</b><small>{offer.delivery_method} · zwrot {offer.return_policy.window_days} dni</small></span><strong>{money(offer.price)}</strong><i>Wybierz</i>
          </button>)}</div>
          {props.filtered.length ? <details className="mobile-filtered"><summary>{props.filtered.length} ofert odrzuconych przez zasady</summary>{props.filtered.map(item => <p key={item.offer.sku}>{item.offer.title}<code>{item.violated_clause}</code></p>)}</details> : null}
        </div>
      </article> : null}

      {purchase ? <article className="agent-message">
        <span className="agent-avatar">M</span>
        <div className="chat-card checkout-chat-card">
          <small>PROPOZYCJA ZAKUPU</small>
          <h2>{String(purchase.proposal.sku ?? 'Wybrany produkt')}</h2>
          <div className="checkout-total"><span>Razem</span><strong>{money(proposalTotal(purchase))}</strong></div>
          <p>Dostawa: {String(purchase.proposal.delivery_method ?? 'paczkomat')} · obietnica {String(purchase.proposal.delivery_promise ?? '')}</p>
          {purchase.status === 'awaiting_human_authorization' ? <button className="mobile-primary" onClick={() => props.onSign(purchase.id, 'cart')}>Zatwierdź ten koszyk</button> : null}
          {purchase.status === 'cart_signed' ? <><div className="verified-line">✓ Cena i produkt podpisane</div><button className="blik-button" onClick={openBlik}><span>BLIK</span> Zapłać w rozmowie</button></> : null}
          {purchase.order_status === 'payment_pending' ? <button className="blik-button" onClick={() => setBlikOpen(true)}><span>BLIK</span> Wpisz kod i potwierdź</button> : null}
          {purchase.order_status === 'payment_failed' ? <button className="mobile-danger" onClick={retryBlik}>Płatność odrzucona · spróbuj ponownie</button> : null}
        </div>
      </article> : null}

      {purchase && ['paid', 'shipped', 'in_paczkomat', 'picked_up', 'return_requested', 'return_in_transit'].includes(purchase.order_status) ? <article className="agent-message">
        <span className="agent-avatar">M</span>
        <div className="chat-card status-chat-card">
          <small>STATUS ZAMÓWIENIA</small>
          <h2>{purchase.order_status.replaceAll('_', ' ')}</h2>
          {purchase.order_status === 'paid' ? <p>Płatność potwierdzona. Sklep przygotowuje zamówienie.</p> : null}
          {purchase.order_status === 'shipped' ? <p>Przesyłka jest w drodze. Będę śledzić ją w tle.</p> : null}
          {purchase.order_status === 'in_paczkomat' ? <div className="locker-code"><span>Paczkomat WAW117M</span><b>482 913</b><small>Kod odbioru</small></div> : null}
          {purchase.order_status === 'picked_up' && !purchase.exception ? <><p>Produkt odebrany i zgodny z podpisanym koszykiem. Co robimy?</p><div className="decision-row"><button className="mobile-primary" onClick={props.onKeep}>Zostawiam</button><button className="mobile-secondary" onClick={props.onReturn}>Zwracam</button></div></> : null}
          {purchase.order_status === 'return_requested' ? <p>Zwrot zaakceptowany. Kod nadania: <b>ML-RETURN-482913</b></p> : null}
          {purchase.order_status === 'return_in_transit' ? <p>Zwrot jest w drodze. Po przyjęciu uruchomię refund automatycznie.</p> : null}
          {props.demo && canAdvance ? <button className="mobile-demo" onClick={props.onAdvance}>Demo · następny etap →</button> : null}
        </div>
      </article> : null}

      {purchase?.exception ? <article className="agent-message">
        <span className="agent-avatar alert-avatar">!</span>
        <div className="chat-card exception-chat-card"><small>{purchase.exception.type === 'ITEM_MISMATCH' ? 'WYKRYTO NIEZGODNOŚĆ' : 'DECYZJA O ZWROCIE'}</small><h2>{purchase.exception.type === 'ITEM_MISMATCH' ? 'Inny produkt' : 'Pełny zwrot'}</h2><p>{purchase.exception.type === 'ITEM_MISMATCH' ? 'Odebrany produkt nie zgadza się z koszykiem, który podpisałeś.' : 'Poprosiłeś o zwrot. Potrzebny jest jeszcze podpis tej dokładnej decyzji.'}</p><div className="mobile-diff"><div><small>MIAŁO BYĆ</small><pre>{JSON.stringify(purchase.exception.evidence.expected, null, 2)}</pre></div><div><small>ODEBRANO</small><pre>{JSON.stringify(purchase.exception.evidence.observed, null, 2)}</pre></div></div>{purchase.exception.resolution_status === 'proposed' ? <button className="mobile-danger" onClick={() => props.onSign(purchase.id, 'resolution')}>Zatwierdź pełny zwrot</button> : <div className="verified-line">✓ Zwrot zatwierdzony</div>}</div>
      </article> : null}

      {isClosed ? <article className="agent-message">
        <span className="agent-avatar">M</span>
        <div className="chat-card closed-chat-card"><small>ZAMKNIĘTE</small><h2>{purchase?.order_status === 'closed_refunded' ? 'Środki zwrócone' : 'Zakup zakończony'}</h2><p>Cała historia, decyzje polityki i podpisy są gotowe jako dowód.</p><button className="mobile-secondary" onClick={props.onEvidence}>Pobierz evidence bundle</button></div>
      </article> : null}

      {props.events.length ? <details className="mobile-audit"><summary>Pełny dziennik działań · {props.events.length}</summary>{props.events.map(event => <div key={event.seq}><span>{event.actor}</span><b>{event.type.replaceAll('_', ' ')}</b><time>{new Date(event.ts).toLocaleTimeString('pl-PL', {hour: '2-digit', minute: '2-digit'})}</time></div>)}</details> : null}
      <p className="mobile-notice">{props.notice}</p>
    </div>

    {!intent ? <footer className="mobile-composer"><button className="voice-button" aria-label="Nagraj wiadomość">●</button><textarea aria-label="Napisz czego potrzebujesz" value={props.prompt} onChange={event => props.setPrompt(event.target.value)}/><button className="send-button" onClick={props.onDraft}>↑</button></footer> : null}

    {blikOpen ? <div className="mobile-sheet-backdrop" role="dialog" aria-modal="true" aria-label="BLIK payment prompt"><div className="mobile-blik-sheet">
      <div className="sheet-handle"/><small>BEZPIECZNA PŁATNOŚĆ · SKLEP DEMO</small><h2>{money(purchase ? proposalTotal(purchase) : 0)}</h2><p>Wpisz sześciocyfrowy kod BLIK. Agent nie widzi ani nie zatwierdza tej decyzji.</p>
      <input value={blikCode} onChange={event => setBlikCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="000 000" aria-label="Sześciocyfrowy kod BLIK"/>
      <button className="blik-confirm" disabled={blikCode.length !== 6 || paying} onClick={confirmBlik}>{paying ? 'Potwierdzam…' : 'Potwierdź w banku (demo)'}</button>
      {props.payUrl ? <a href={props.payUrl} target="_blank" rel="noreferrer">Otwórz osobny ekran banku</a> : null}
      <button className="cancel-payment" onClick={() => setBlikOpen(false)}>Anuluj</button>
    </div></div> : null}
  </section>
}
