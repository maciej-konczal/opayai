import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { api, approveContext } from './api'
import { MobileChat } from './MobileChat'
import type { Intent, LedgerEvent, Offer, Purchase } from './types'

const money = (grosze: number) => new Intl.NumberFormat('pl-PL', {style: 'currency', currency: 'PLN'}).format(grosze / 100)
const stageFor = (type: string) => type.includes('intent') ? 'INTENT' : type.includes('proposal') ? 'DECIDE' : type.includes('policy') ? 'APPROVE' : type.includes('payment') ? 'PURCHASE' : type.includes('refund') || type.includes('resolution') ? 'RESOLVE' : 'TRACK'

export function App() {
  const [prompt, setPrompt] = useState('Kup mi zestaw opon zimowych 205/55 R16 do 1600 zł, min. 14 dni na zwrot.')
  const [intent, setIntent] = useState<Intent | null>(null)
  const [offers, setOffers] = useState<Offer[]>([])
  const [filtered, setFiltered] = useState<{offer: Offer; violated_clause: string}[]>([])
  const [purchase, setPurchase] = useState<Purchase | null>(null)
  const [events, setEvents] = useState<LedgerEvent[]>([])
  const [sheet, setSheet] = useState<'intent' | 'cart' | 'payment' | 'resolution' | 'evidence' | null>(null)
  const [payUrl, setPayUrl] = useState<string | null>(null)
  const [notice, setNotice] = useState('Wpisz zamiar. Agent przygotuje propozycję; podpis należy do Ciebie.')
  const demo = new URLSearchParams(location.search).get('demo') === '1'

  useEffect(() => api.events(event => {
    setEvents(previous => previous.some(e => e.seq === event.seq) ? previous : [...previous, event])
    if (event.type === 'notification' && 'Notification' in window && Notification.permission === 'granted') {
      new Notification('MandateLoop', {body: String(event.payload.message ?? 'Nowe zdarzenie zakupu')})
    }
  }), [])
  useEffect(() => { if (intent?.status === 'open') void loadProducts(intent.id) }, [intent?.id, intent?.status])

  async function loadProducts(id = intent?.id) {
    const data = await api.products(id)
    setOffers(data.offers); setFiltered(data.filtered_out)
  }
  async function draft(surface: 'desktop' | 'mobile' = 'desktop') {
    try {
      if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission()
      const next = await api.draft(prompt); setIntent(next); if (surface === 'desktop') setSheet('intent'); setNotice('Mandat jest szkicem. Sprawdź warunki i podpisz go lokalnie.')
    } catch (error) { setNotice(String(error)) }
  }
  async function sign(id: string, type: 'intent' | 'cart' | 'resolution') {
    try {
      await approveContext(id, type)
      if (type === 'intent') { const next = {...intent!, status: 'open' as const}; setIntent(next); await loadProducts(next.id); setNotice('Mandat otwarty. Oferty zostały odfiltrowane przez politykę.') }
      if (type === 'cart') { await refreshPurchase(); setNotice('Koszyk związany z Twoim podpisem. Wybierz BLIK.') }
      if (type === 'resolution') { await refreshPurchase(); setNotice('Zwrot zatwierdzony. Kod nadania pojawił się w powiadomieniach.') }
      setSheet(null)
    } catch (error) { setNotice(String(error)) }
  }
  async function buy(offer: Offer, surface: 'desktop' | 'mobile' = 'desktop') {
    if (!intent) return
    try { const result = await api.purchase(intent.id, offer.sku); setPurchase({id: result.purchase_id, intent_id: intent.id, status: result.status, order_status: 'created', proposal: result.proposal}); if (surface === 'desktop') setSheet('cart'); setNotice('Propozycja czeka na Twój podpis — agent nie może zapłacić.') } catch (error) { setNotice(String(error)) }
  }
  async function refreshPurchase() { if (purchase) { const next = await api.getPurchase(purchase.id); setPurchase(next); setEvents(previous => [...previous, ...(next.events ?? [])].filter((event, index, all) => all.findIndex(e => e.seq === event.seq) === index)) } }
  async function chooseBlik(surface: 'desktop' | 'mobile' | unknown = 'desktop') { if (!purchase) return; const mode = surface === 'mobile' ? 'mobile' : 'desktop'; try { const data = await api.rail(purchase.id); setPayUrl(data.pay_url); const next = await api.getPurchase(purchase.id); setPurchase(next); if (mode === 'desktop') setSheet('payment') } catch (error) { setNotice(String(error)) } }
  async function confirmBlik(code: string) { if (!purchase) return; try { await api.confirmBlik(purchase.id, code); const next = await api.getPurchase(purchase.id); setPurchase(next); setEvents(previous => [...previous, ...(next.events ?? [])].filter((event, index, all) => all.findIndex(item => item.seq === event.seq) === index)); setNotice('BLIK potwierdzony. Agent śledzi zamówienie w tle.') } catch (error) { setNotice(String(error)); throw error } }
  async function retryBlik() { if (!purchase) return; const data = await api.retry(purchase.id); setPayUrl(data.pay_url); const next = await api.getPurchase(purchase.id); setPurchase(next); setNotice('Nowa sesja BLIK jest gotowa.') }
  async function advancePurchase() { if (!purchase?.order?.id) return; await api.advance(purchase.order.id); await refreshPurchase() }
  async function keepPurchase() { if (!purchase) return; await api.satisfied(purchase.id); await refreshPurchase() }
  async function returnPurchase() { if (!purchase) return; await api.initiateReturn(purchase.id, 'Nie chcę zatrzymać produktu'); await api.resolution(purchase.id); await approveContext(purchase.id, 'resolution'); await refreshPurchase(); setNotice('Zwrot podpisany. Agent prowadzi go dalej w tej rozmowie.') }
  async function revokeIntent() { if (!intent) return; const revoked = await api.revoke(intent.id); setIntent(revoked); setNotice('Mandat cofnięty. Kolejne działania agentów zostaną zablokowane.') }
  async function downloadEvidence() { if (!purchase) return; const data = await api.evidence(purchase.id); const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'})); const anchor = document.createElement('a'); anchor.href = href; anchor.download = `mandateloop-evidence-${purchase.id}.json`; anchor.click(); URL.revokeObjectURL(href) }
  const progress = intent ? Math.min(100, (intent.spent_total / intent.constraints.max_total) * 100) : 0
  const canAdvance = purchase?.order?.id && ['paid', 'shipped', 'in_paczkomat', 'return_requested', 'return_in_transit'].includes(purchase.order_status)

  return <main className="shell">
    <MobileChat prompt={prompt} setPrompt={setPrompt} notice={notice} intent={intent} offers={offers} filtered={filtered} purchase={purchase} events={events} payUrl={payUrl} demo={demo} onDraft={() => draft('mobile')} onSign={sign} onBuy={offer => buy(offer, 'mobile')} onStartBlik={() => chooseBlik('mobile')} onConfirmBlik={confirmBlik} onRetryBlik={retryBlik} onAdvance={advancePurchase} onKeep={keepPurchase} onReturn={returnPurchase} onEvidence={downloadEvidence} onRevoke={revokeIntent}/>
    <header className="topbar"><div className="brand"><i/>MANDATELOOP</div><p>Consent-first agentic commerce · <b>human present</b></p><span className="mode">DEMO / PLN</span></header>
    <section className="layout">
      <aside className="chat panel"><p className="eyebrow">01 · Agent rail</p><h1>Give an agent<br/>a mandate,<br/><em>not a wallet.</em></h1><textarea value={prompt} onChange={e => setPrompt(e.target.value)} aria-label="Purchase intent"/><button className="ink-button" onClick={() => draft('desktop')}>Utwórz mandat <span>↗</span></button><p className="notice">{notice}</p>
        <div className="offer-stack"><p className="eyebrow">Policy-filtered offers</p>{offers.map(offer => <article className="offer" key={offer.sku}><div><b>{offer.title}</b><small>{offer.delivery_method} · {offer.return_policy.window_days} dni na zwrot</small></div><strong>{money(offer.price)}</strong><button onClick={() => buy(offer)} disabled={!intent || intent.status !== 'open'}>Kup</button></article>)}
        {filtered.length > 0 && <details><summary>{filtered.length} odrzucone przez politykę</summary>{filtered.map(({offer, violated_clause}) => <p className="filtered" key={offer.sku}>{offer.title}<code>{violated_clause}</code></p>)}</details>}</div>
      </aside>

      <section className="feed panel"><div className="feed-head"><div><p className="eyebrow">02 · Live evidence ledger</p><h2>Lifecycle, not a checkout.</h2></div><button className="quiet" onClick={refreshPurchase}>Odśwież ↻</button></div><div className="ledger">{events.length === 0 ? <p className="empty">Zdarzenia, decyzje polityki i powiadomienia pojawią się tutaj w kolejności hash-chain.</p> : events.map(event => <article className={`event ${event.type === 'policy_block' ? 'blocked' : ''}`} key={event.seq}><span className="dot"/><div><small>{stageFor(event.type)} · {event.actor}</small><b>{event.type.replaceAll('_', ' ')}</b><p>{event.payload.message as string ?? event.payload.clause as string ?? JSON.stringify(event.payload)}</p></div><time>{new Date(event.ts).toLocaleTimeString('pl-PL', {hour:'2-digit', minute:'2-digit'})}</time></article>)}</div>
        {purchase && <div className="action-row"><button className="quiet" onClick={() => setSheet('evidence')}>Dowód zakupu</button>{canAdvance && <button className="ink-button" onClick={async () => { await api.advance(purchase.order!.id); await refreshPurchase()}}>Demo: następny etap</button>}{purchase.order_status === 'picked_up' && !purchase.exception && <button className="ink-button" onClick={async () => { await api.satisfied(purchase.id); await refreshPurchase()}}>Zostawiam produkt</button>}{purchase.exception && <button className="danger-button" onClick={async () => { await api.resolution(purchase.id); setSheet('resolution') }}>Rozwiąż wyjątek</button>}{purchase.order_status === 'payment_failed' && <button className="danger-button" onClick={async () => { const data = await api.retry(purchase.id); setPayUrl(data.pay_url); setSheet('payment'); await refreshPurchase() }}>Spróbuj ponownie</button>}</div>}</section>

      <aside className="mandate panel"><p className="eyebrow">03 · Permission slip</p>{intent ? <><div className={`seal ${intent.status}`}><span>{intent.status === 'open' ? 'OTWARTY' : intent.status.toUpperCase()}</span></div><h2>{intent.description}</h2><dl><div><dt>Kategorie</dt><dd>{intent.constraints.categories.join(', ')}</dd></div><div><dt>Zwrot</dt><dd>min. {intent.constraints.min_return_window_days} dni</dd></div><div><dt>Rail</dt><dd>BLIK lite</dd></div><div><dt>Wygasa</dt><dd>{new Date(intent.constraints.expiry).toLocaleString('pl-PL')}</dd></div></dl><div className="budget"><div><span>Wydano</span><b>{money(intent.spent_total)} / {money(intent.constraints.max_total)}</b></div><i><i style={{width: `${progress}%`}}/></i></div><button className="revoke" onClick={async () => { const revoked = await api.revoke(intent.id); setIntent(revoked); setNotice('Mandat cofnięty. Kolejne działania agentów zostaną zablokowane.') }}>COFNIJ MANDAT</button></> : <p className="empty">Podpisany mandat będzie tutaj czytelny z drugiego końca pokoju.</p>}
      <div className="notifications"><p className="eyebrow">Powiadomienia</p>{events.filter(event => event.type === 'notification').slice(-4).reverse().map(event => <p key={event.seq}>{event.payload.message as string}</p>)}</div>{demo && purchase?.order?.id && <div className="demo"><p className="eyebrow">Fault injection</p><button onClick={() => api.fault(purchase.order!.id, 'wrong_item')}>Wrong item</button><button onClick={() => api.fault(purchase.order!.id, 'decline_payment')}>Decline BLIK</button></div>}</aside>
    </section>
    {sheet && <div className="backdrop" role="dialog" aria-modal="true"><section className="sheet"><button className="close" onClick={() => setSheet(null)}>×</button>{sheet === 'intent' && intent && <><p className="eyebrow">Human authorization</p><h2>Podpisujesz zamiar,<br/>nie pusty czek.</h2><p>Podpis jest związany z ograniczeniami: {money(intent.constraints.max_total)}, {intent.constraints.categories.join(', ')}, zwrot min. {intent.constraints.min_return_window_days} dni.</p><button className="ink-button" onClick={() => sign(intent.id, 'intent')}>Podpisz lokalnie ↗</button></>}{sheet === 'cart' && purchase && <><p className="eyebrow">Exact-cart approval</p><h2>Ten koszyk,<br/>ta cena.</h2><pre>{JSON.stringify(purchase.proposal, null, 2)}</pre><button className="ink-button" onClick={() => sign(purchase.id, 'cart')}>Podpisz koszyk ↗</button><button className="rail live" onClick={chooseBlik}>BLIK lite <span>aktywny</span></button><button className="rail" disabled>Card <span>slot</span></button><button className="rail" disabled>USDC <span>slot</span></button></>}{sheet === 'payment' && <><p className="eyebrow">Out-of-band payment</p><h2>Potwierdź BLIK<br/>na telefonie.</h2><div className="qr">{payUrl ? <QRCodeSVG value={payUrl} size={128} bgColor="#e9e8dd" fgColor="#172018" level="M"/> : null}<b>{payUrl?.split('/').pop()}</b></div><a className="pay-link" href={payUrl ?? '#'} target="_blank" rel="noreferrer">Otwórz stronę potwierdzenia ↗</a><button className="quiet" onClick={async () => { await refreshPurchase(); setSheet(null) }}>Wróciłem z telefonu</button></>}{sheet === 'resolution' && purchase && <><p className="eyebrow">Resolution approval</p><h2>Niezgodność<br/>jest dowodem.</h2><div className="diff"><div><small>OCZEKIWANO</small><pre>{JSON.stringify(purchase.exception?.evidence.expected, null, 2)}</pre></div><div><small>ODEBRANO</small><pre>{JSON.stringify(purchase.exception?.evidence.observed, null, 2)}</pre></div></div><button className="danger-button" onClick={() => sign(purchase.id, 'resolution')}>Podpisz pełny zwrot</button></>}{sheet === 'evidence' && purchase && <><p className="eyebrow">Close-out receipt</p><h2>Evidence bundle.</h2><p>Podpisane mandaty, pełny hash-chain, próby płatności, diff oraz atrybucja agenta w jednym JSON-ie.</p><button className="ink-button" onClick={downloadEvidence}>Pobierz dowód .json</button></>}</section></div>}
  </main>
}
