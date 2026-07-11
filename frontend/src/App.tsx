import { useEffect, useRef, useState } from 'react'
import { newTransactionId } from './lib/transaction'
import { askAgent } from './lib/agent'

type Step = 'start' | 'recommendations' | 'approval' | 'passkey' | 'ordered' | 'delivered' | 'kept' | 'returning' | 'returned'

const options = [
  { id: 'of_5', name: 'MacBook Air 13”', details: 'M4 · 16GB · 512GB', price: '4,999 PLN', note: 'Best for university', art: 'air' },
  { id: 'of_6', name: 'MacBook Pro 14”', details: 'M4 · 16GB · 512GB', price: '7,999 PLN', note: 'For heavier creative work', art: 'pro' },
  { id: 'of_7', name: 'Lenovo Yoga Slim 7', details: 'Ryzen 7 · 16GB · 512GB', price: '3,899 PLN', note: 'Best value', art: 'lenovo' },
]

export default function App() {
  const [step, setStep] = useState<Step>('start')
  const [request, setRequest] = useState('I want a laptop for university')
  const [draft, setDraft] = useState('I want a laptop for university')
  const [followUps, setFollowUps] = useState<Array<{ prompt: string, response: string }>>([])
  const [firstReply, setFirstReply] = useState('')
  const [checkout, setCheckout] = useState<{ intentId?: string, cartId?: string, orderId?: string }>({})
  const chatRef = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState(0)
  const [orderId, setOrderId] = useState('')
  const product = options[selected]
  const progress = { start: 0, recommendations: 1, approval: 2, passkey: 2.5, ordered: 3, delivered: 4, kept: 5, returning: 5, returned: 6 }[step]
  const send = () => {
    if (!draft.trim()) return
    if (step === 'start') { setRequest(draft); askAgent(draft).then(result => { setFirstReply(result.text); const started = result.results.find(item => item.name === 'start_purchase')?.output.intent as { id?: string } | undefined; if (started?.id) setCheckout({ intentId: started.id }) }).catch(() => {}); setStep('recommendations') }
    else { const prompt = draft; setFollowUps(previous => [...previous, { prompt, response: 'Thinking…' }]); askAgent(prompt).then(result => setFollowUps(previous => previous.map(item => item.prompt === prompt && item.response === 'Thinking…' ? { ...item, response: result.text || 'I’ve noted that and will keep it in mind.' } : item))).catch(() => setFollowUps(previous => previous.map(item => item.prompt === prompt && item.response === 'Thinking…' ? { ...item, response: 'I couldn’t reach the agent just now. Please try again.' } : item))) }
    setDraft('')
  }
  const pick = (i: number) => { setSelected(i); if (checkout.intentId) askAgent(`The user selected offer ${options[i].id} for intent ${checkout.intentId}. Create the cart and run policy checks, but do not pay.`).then(result => { const cart = result.results.find(item => item.name === 'select_offer')?.output.cart as { id?: string } | undefined; if (cart?.id) setCheckout(current => ({ ...current, cartId: cart.id })) }).catch(() => {}); setStep('approval') }
  const authorize = () => { if (checkout.cartId) askAgent(`The user explicitly approved cart ${checkout.cartId}. Record the approval only; do not pay yet.`).catch(() => {}); setStep('passkey') }
  const verifyPasskey = () => { const cartId = checkout.cartId; if (cartId) askAgent(`The user completed their Apple Passkey for cart ${cartId}. Complete the passkey step-up and settle payment.`).then(result => { const order = result.results.find(item => item.name === 'complete_passkey_and_pay')?.output as { id?: string }; if (order?.id) { setOrderId(order.id); setCheckout(current => ({ ...current, orderId: order.id })) } else setOrderId(newTransactionId()); setStep('ordered') }).catch(() => { setOrderId(newTransactionId()); setStep('ordered') }); else { setOrderId(newTransactionId()); setStep('ordered') } }
  const deliver = () => { const order = checkout.orderId; if (order) askAgent(`Advance order ${order} through shipping to delivered.`).catch(() => {}); setStep('delivered') }
  const returnOrder = () => { const order = checkout.orderId; if (order) askAgent(`The user wants to return delivered order ${order}. Request the return.`).catch(() => {}); setStep('returned') }

  useEffect(() => {
    requestAnimationFrame(() => chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' }))
  }, [step, followUps])

  return <main>
    <section className="app-shell">
      <header><div className="ios-status"><b>13:54</b><span>▮▮▮ &nbsp;5G&nbsp; ▰</span></div><button className="header-button" aria-label="Open menu">☰</button><div className="channel"><img src="/boski-header-mark.png" alt="Boski" style={{ objectFit: 'contain', objectPosition: 'center', filter: 'none' }}/><b>General</b></div><button className="header-button archive" aria-label="Open archive">▰</button></header>
      <div className="chat" aria-live="polite" ref={chatRef}>
        <div className="date">TODAY</div>
        <Bot><p>Hey Franek! What can I help you find today?</p></Bot>
        {step !== 'start' && <User>{request}</User>}
        {progress >= 1 && <Recommendations onPick={pick} selected={selected} locked={progress > 1} intro={firstReply} />}
        {progress >= 2 && <><User>I’ll go with the {product.name}</User><Approval product={product} onAuthorize={authorize} locked={progress > 2} passkeyPending={step === 'passkey'} /></>}
        {step === 'passkey' && <><User>Authorise payment</User><Passkey onVerify={verifyPasskey} /></>}
        {progress >= 3 && <Ordered product={product} orderId={orderId} onDeliver={deliver} delivered={progress > 3} />}
        {progress >= 4 && <Delivered product={product} onKeep={() => setStep('kept')} onReturn={() => setStep('returning')} locked={progress > 4} />}
        {step === 'kept' && <Bot><p>Perfect — I’ve marked it as kept and saved your receipt.</p><div className="receipt">✓ &nbsp; Receipt saved <span>{orderId}</span></div></Bot>}
        {(step === 'returning' || step === 'returned') && <><User>I’d like to start a return</User><ReturnFlow product={product} confirmed={step === 'returned'} onConfirm={returnOrder} /></>}
        {followUps.map((item, index) => <div key={`${item.prompt}-${index}`}><User>{item.prompt}</User><Bot><p>{item.response}</p></Bot></div>)}
      </div>
      <footer>
        {step === 'start' && <div className="suggestions"><button onClick={() => setDraft('I want the newest MacBook Air 13”')}>Newest MacBook Air</button><button onClick={() => setDraft('I need a laptop for university')}>Laptop for university</button></div>}
        <div className="composer"><input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => e.key === 'Enter' && send()} placeholder="Message Boski..." aria-label="Your message"/><button onClick={send} aria-label="Send message">↑</button></div>
        {step !== 'start' && <p className="secure">✦ Your agent only acts when you approve</p>}
      </footer>
    </section>
  </main>
}

function Bot({ children }: { children: React.ReactNode }) { return <div className="bot-row"><div className="bot-avatar">✦</div><div className="bubble bot-bubble">{children}</div></div> }
function User({ children }: { children: React.ReactNode }) { return <div className="user-row"><div className="bubble user-bubble">{children}</div></div> }

function Recommendations({ onPick, selected, locked, intro }: { onPick: (i: number) => void, selected: number, locked: boolean, intro: string }) { return <Bot><p>{intro || 'I found three great options. All have 16GB RAM, excellent battery life and easy returns.'}</p><div className="options">{options.map((o, i) => <button className={`option ${locked && i === selected ? 'picked' : ''}`} key={o.name} onClick={() => onPick(i)} disabled={locked}><div className={`device ${o.art}`}><span></span></div><div><small>{o.note}</small><h3>{o.name}</h3><p>{o.details}</p><b>{o.price}</b></div><em>{locked && i === selected ? '✓' : '›'}</em></button>)}</div><p className="tiny">Prices and availability checked just now.</p></Bot> }

function Approval({ product, onAuthorize, locked, passkeyPending }: { product: typeof options[0], onAuthorize: () => void, locked: boolean, passkeyPending: boolean }) { return <Bot><p>Great choice. Here’s the order I’m ready to place:</p><div className="approval"><div className={`device mini ${product.art}`}><span></span></div><div><h3>{product.name}</h3><p>{product.details}</p><b>{product.price}</b><small>Delivery tomorrow · Free returns</small></div></div><div className="consent"><b>{passkeyPending ? 'Passkey confirmation needed' : locked ? 'Payment approved' : 'Approval needed'}</b><span>I’ll only place this exact order for this amount.</span><button onClick={onAuthorize} disabled={locked}>{locked ? 'Payment authorised ✓' : <>Authorise payment <i>→</i></>}</button></div></Bot> }

function Passkey({ onVerify }: { onVerify: () => void }) { return <Bot><p>Confirm it’s you with your Apple Passkey.</p><div style={{ background: '#fff', border: '1px solid #deded8', borderRadius: 11, padding: 13, marginTop: 10, textAlign: 'center' }}><div style={{ fontSize: 26, lineHeight: 1, marginBottom: 7 }}></div><b style={{ display: 'block', fontSize: 12 }}>Sign in with Apple Passkey</b><span style={{ display: 'block', fontSize: 9, color: '#7c807b', marginTop: 4 }}>Use Face ID or your device passcode</span><button onClick={onVerify} style={{ width: '100%', marginTop: 12, padding: '10px 8px', borderRadius: 7, background: '#111', color: '#fff', fontSize: 11, fontWeight: 600 }}>Continue with Passkey</button></div><p className="tiny">Your passkey stays securely on your device.</p></Bot> }

function Ordered({ product, orderId, onDeliver, delivered }: { product: typeof options[0], orderId: string, onDeliver: () => void, delivered: boolean }) { return <><User>Authorise payment</User><Bot><div className="success">✓</div><p><b>Payment approved.</b><br/>Your {product.name} is on its way.</p><div className="tracking"><span>ORDER CONFIRMED</span><b>{orderId}</b><p>● &nbsp; Ordered just now</p><p>○ &nbsp; Arrives tomorrow, by 18:00</p></div><button className="demo-button" onClick={onDeliver} disabled={delivered}>{delivered ? 'Delivery update received ✓' : 'Simulate delivery update →'}</button></Bot></> }

function Delivered({ product, onKeep, onReturn, locked }: { product: typeof options[0], onKeep: () => void, onReturn: () => void, locked: boolean }) { return <Bot><p>Good news — your <b>{product.name}</b> was delivered at 14:32.</p><p>How did it go?</p><div className="actions"><button onClick={onKeep} disabled={locked}><span>♥</span><b>{locked ? 'Kept ✓' : 'Keep it'}</b></button><button onClick={onReturn} disabled={locked}><span>↩</span><b>Start a return</b><small>Free until 1 Aug</small></button></div></Bot> }

function ReturnFlow({ product, confirmed, onConfirm }: { product: typeof options[0], confirmed: boolean, onConfirm: () => void }) { return <Bot>{confirmed ? <><div className="success">✓</div><p><b>Your return is booked.</b><br/>A courier will collect your {product.name} tomorrow, 09:00–17:00.</p><div className="tracking"><span>REFUND</span><b>{product.price}</b><p>● &nbsp; Return label emailed</p><p>○ &nbsp; Refund issued after collection</p></div></> : <><p>No problem — your return is free and available until 1 Aug.</p><div className="return-card"><b>Free courier pickup</b><span>Tomorrow, 09:00–17:00</span><small>Return label will be emailed to you.</small></div><button className="demo-button" onClick={onConfirm}>Confirm return pickup →</button></>}</Bot> }
