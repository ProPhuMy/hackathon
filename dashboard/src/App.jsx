import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import './App.css'
const Fridge3D = lazy(() => import('./Fridge3D.jsx'))

const inventory = [
  { id: '043', name: 'Oat milk', owner: 'Viet', kind: 'carton', color: '#c9d7ab', time: '09:12' },
  { id: '044', name: 'Lunch box', owner: 'Khang', kind: 'box', color: '#e3a077', time: '09:21' },
  { id: '045', name: 'Greek yogurt', owner: 'Phong', kind: 'jar', color: '#e5dca4', time: '09:25' },
  { id: '046', name: 'Cold brew', owner: 'Dang', kind: 'bottle', color: '#a27f60', time: '09:24' },
  { id: '047', name: 'Apples', owner: 'Khang', kind: 'fruit', color: '#b6bf76', time: '09:27' },
  { id: '048', name: 'Orange juice', owner: 'Viet', kind: 'carton', color: '#e6b55c', time: '09:29' },
]
const events = [
  { time: '09:34', action: 'TAKE', item: 'Milk carton', person: 'Dang', owner: 'Viet', result: 'Mismatch', confidence: '90%' },
  { time: '09:31', action: 'PUT', item: 'Pasta salad', person: 'Phong', owner: 'Phong', result: 'Verified', confidence: '96%' },
  { time: '09:28', action: 'TAKE', item: 'Sandwich', person: 'Unknown', owner: 'Khang', result: 'Uncertain', confidence: '42%' },
  { time: '09:24', action: 'PUT', item: 'Cold brew', person: 'Dang', owner: 'Dang', result: 'Verified', confidence: '94%' },
  { time: '09:21', action: 'PUT', item: 'Lunch box', person: 'Khang', owner: 'Khang', result: 'Verified', confidence: '98%' },
]

function Modal({ title, onClose, children }) {
  const ref = useRef(null)
  const openerRef = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog.open) {
      openerRef.current = document.activeElement
      dialog.showModal()
    }
    return () => {
      // Route removal detaches the dialog; restore its opener explicitly.
      // Calling close() here also fires onClose during StrictMode's effect replay.
      if (openerRef.current?.isConnected) openerRef.current.focus({ preventScroll: true })
    }
  }, [])
  return <dialog ref={ref} onCancel={onClose} onClose={onClose} aria-labelledby="dialog-title" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div className="panel-header"><div><span className="eyebrow">FRIDGE— / CONTROL ROOM</span><h2 id="dialog-title">{title}</h2></div><button className="close-button" onClick={onClose} aria-label="Close panel">×</button></div>
    {children}
  </dialog>
}

function App() {
  const [travel, setTravel] = useState(false)
  const [phase, setPhase] = useState('idle')
  const [modelReady, setModelReady] = useState(false)
  const [modelFailed, setModelFailed] = useState(false)
  const enterRef = useRef(null)
  const returnRef = useRef(null)
  const wasTravelling = useRef(false)
  const immersive = travel || phase !== 'idle'
  const onModelReady = useCallback(() => setModelReady(true), [])
  const onModelFailure = useCallback(() => { setModelFailed(true); setTravel(false); setPhase('idle') }, [])
  const startTravel = useCallback(() => setTravel(true), [])
  const go = useNavigate()
  const pathname = useRouterState({ select: state => state.location.pathname })
  const sectionNames = { '/inventory': 'Inventory', '/history': 'History', '/alerts': 'Alerts', '/people': 'People' }
  const panel = sectionNames[pathname] || (pathname.startsWith('/items/') ? 'Item details' : pathname.startsWith('/events/') ? 'Event details' : null)
  const selected = panel === 'Item details' ? inventory.find(i => i.id === pathname.split('/')[2]) : panel === 'Event details' ? events.find(e => e.time.replace(':', '') === pathname.split('/')[2]) : null
  const selectedId = pathname.startsWith('/items/') ? pathname.split('/')[2] : null
  function setPanel(value) { return go({ to: value ? '/' + value.toLowerCase() : '/' }) }
  const [query, setQuery] = useState('')
  const [owner, setOwner] = useState('Everyone')
  const [people, setPeople] = useState(['Khang', 'Viet', 'Dang', 'Phong'])
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [notice, setNotice] = useState('')
  const visibleItems = inventory.filter(i => (owner === 'Everyone' || owner === i.owner) && `${i.name} ${i.owner}`.toLowerCase().includes(query.toLowerCase()))
  function navigate(value) { setPanel(value); setQuery(''); setOwner('Everyone'); setAdding(false) }
  function closePanel() { setPanel(null) }
  function inspect(item) {
    go({ to: '/items/$itemId', params: { itemId: item.id } })
  }

  useEffect(() => {
    if (travel) {
      wasTravelling.current = true
      returnRef.current?.focus({ preventScroll: true })
    }
  }, [travel])

  useEffect(() => {
    if (phase === 'floating') {
      const active = document.activeElement
      if (!active || active === document.body || !active.isConnected) {
        returnRef.current?.focus({ preventScroll: true })
      }
    } else if (phase === 'idle' && wasTravelling.current) {
      wasTravelling.current = false
      enterRef.current?.focus({ preventScroll: true })
    }
  }, [phase])

  useEffect(() => {
    const onKey = event => {
      if (panel || !travel) return
      if (event.key === 'Escape') { event.preventDefault(); setTravel(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [travel, panel])

  return <div className={`app ${immersive ? 'is-immersive' : ''}`}>
    <section className="fridge-scene" aria-label="Interactive mini fridge">
      <Suspense fallback={null}>
        <Fridge3D
          travel={travel}
          items={inventory}
          selectedId={selectedId}
          onTravel={startTravel}
          onInspect={id => go({ to: '/items/$itemId', params: { itemId: id } })}
          onPhase={setPhase}
          onReady={onModelReady}
          onFailure={onModelFailure}
        />
      </Suspense>
    </section>
    <header className="site-header outside-ui" inert={immersive}>
      <a href="#" className="wordmark" onClick={e => { e.preventDefault(); closePanel(); setTravel(false) }} aria-label="Fridge home">fridge<span>—</span></a>
      <nav aria-label="Main navigation">{['Inventory', 'History', 'Alerts', 'People'].map((name, i) => <Link key={name} to={'/' + name.toLowerCase()} aria-haspopup="dialog"><span className="nav-index">0{i + 1}</span>{name}{name === 'Alerts' && <span className="alert-count">2</span>}</Link>)}</nav>
    </header>
    <div className="system-status outside-ui" inert={immersive}><span className="status-dot"/> LOCAL DEMO<span className="status-caption">ONE FRIDGE. FOUR ROOMMATES.</span></div>
    <main className="room">
      <section className="intro outside-ui" aria-label="Welcome" inert={immersive}>
        <span className="eyebrow">A SHARED FRIDGE, IN ORBIT.</span>
        <h1>CLICK TO<br/>INTERACT.</h1>
        <p>Good food. Questionable roommates.<br/>Somewhere in deep space, we keep track of both.</p>
        <button
          ref={enterRef}
          className="interact-link"
          onClick={modelFailed ? () => navigate('Inventory') : startTravel}
          disabled={!modelReady && !modelFailed}
          aria-expanded={immersive}
          aria-controls="space-journey"
        >
          {modelFailed ? (
            'Browse inventory'
          ) : (
            <>
              {modelReady ? 'Open the wormhole' : 'Charging the wormhole…'}{' '}
              <span aria-hidden="true">↗</span>
            </>
          )}
        </button>
        {modelFailed && <p role="status">3D preview unavailable. Your inventory is still here.</p>}
      </section>
      <div className="fridge-caption outside-ui" aria-hidden={immersive}><span className="status-dot"/>DRIFTING. READY WHEN YOU ARE.<span>FRIDGE / 001</span></div>
      <div className="side-note outside-ui" aria-hidden={immersive}>NO TAGS. NO GUESSWORK. JUST GRAVITY.</div>
    </main>
    <div id="space-journey" inert={!immersive} aria-hidden={!immersive}>
      <button ref={returnRef} className="exit-fridge" onClick={() => setTravel(false)} disabled={!travel}>
        <span aria-hidden="true">↖</span> RETURN HOME <kbd>ESC</kbd>
      </button>
      <div className="interior-heading">
        <span className="status-dot"/> FRIDGE / 001 · CONTENTS ADRIFT <span>ILLUSTRATIVE INVENTORY</span>
      </div>
      <div className="journey-status" role="status">
        {phase === 'pulling' ? 'SOMETHING IS PULLING.' :
         phase === 'wormhole' ? 'FOLDING SPACE.' :
         phase === 'emerging' ? 'ARRIVING. BRACE FOR IMPACT.' :
         phase === 'returning' ? 'HEADING HOME.' : ''}
      </div>
      <div
        className={`floating-content ${phase === 'floating' ? 'is-visible' : ''}`}
        inert={phase !== 'floating'}
      >
        <div className="floating-header">
          <h2 className="floating-heading">Everything that was inside.</h2>
          <p className="floating-hint">Select a floating item to see whose it is.</p>
        </div>
        <div className="floating-items" role="group" aria-label="Floating items">
          {inventory.map(item => (
            <button key={item.id} onClick={() => inspect(item)}>
              <span className="item-marker" style={{ background: item.color }}/>
              <span>{item.name}<small>{item.owner}’s</small></span>
              <span aria-hidden="true">↗</span>
            </button>
          ))}
        </div>
      </div>
    </div>
    <footer className="outside-ui" inert={immersive}><span>BUILT FOR SHARING.<br/><strong>NOT STEALING.</strong></span><button onClick={() => navigate('Alerts')} className="latest-event"><span className="event-dot"/> <span>LATEST SIGNAL <strong>Someone took Viet’s milk.</strong></span><span aria-hidden="true">↗</span></button><span className="footer-meta">FRIDGE TRACKER © 2026<br/>ILLUSTRATIVE DEMO DATA</span></footer>
    <Outlet />
    {panel && <Modal title={panel} onClose={closePanel}>
      {panel === 'Inventory' && <><p className="panel-copy">What’s inside, and who it belongs to.</p><div className="filters"><label className="search-label">Search<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find an item or owner…"/></label><label>Owner<select value={owner} onChange={e => setOwner(e.target.value)}>{['Everyone', ...people].map(p => <option key={p}>{p}</option>)}</select></label></div><div className="inventory-list">{visibleItems.map(item => <button key={item.id} className="inventory-item" onClick={() => inspect(item)}><span className={`food-mini ${item.kind}`} style={{background: item.color}}/><span><strong>{item.name}</strong><small>Owner · {item.owner}</small></span><span className="item-code">0{item.id} ↗</span></button>)}</div>{visibleItems.length === 0 && <p className="empty-state">No items match. Try another name or owner.</p>}<p className="demo-note">{visibleItems.length} of {inventory.length} items · Demo inventory</p></>}
      {panel === 'History' && <><p className="panel-copy">Every put. Every take. Nothing swept under the rug.</p><label className="search-label">Search events<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search by person, item or action…"/></label><div className="table-scroll"><table><thead><tr>{['Time', 'Action', 'Item', 'Person', 'Result'].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{events.filter(e => Object.values(e).join(' ').toLowerCase().includes(query.toLowerCase())).map(e => <tr key={e.time}><td>{e.time}</td><td><span className="action-tag">{e.action}</span></td><td>{e.item}</td><td>{e.person}</td><td><span className={`result ${e.result.toLowerCase()}`}>{e.result}</span></td></tr>)}</tbody></table></div></>}
      {panel === 'Alerts' && <><p className="panel-copy">A signal, not a verdict. Here’s what needs a closer look.</p>{events.filter(e => e.result !== 'Verified').map(e => <article className={`alert-card ${e.result.toLowerCase()}`} key={e.time}><span className="eyebrow">{e.result === 'Mismatch' ? '01 / OWNERSHIP MISMATCH' : '02 / UNCERTAIN IDENTITY'}</span><h3>{e.result === 'Mismatch' ? 'Who took Viet’s milk?' : 'A sandwich left. Identity unclear.'}</h3><p>{e.time} · Owner: {e.owner} · {e.result === 'Mismatch' ? `Taker: ${e.person}` : 'Person not reliably recognized'}</p><button onClick={() => { go({ to: '/events/$eventId', params: { eventId: e.time.replace(':', '') } }) }}>Inspect event ↗</button></article>)}</>}
      {panel === 'People' && <><p className="panel-copy">Familiar faces in a shared space.</p><div className="people-list">{people.map((p, i) => <div className="person" key={p}><span className="avatar">{p[0]}</span><strong>{p}</strong><span className="person-state">{i < 4 ? 'DEMO PROFILE' : 'AWAITING ENROLLMENT'}</span></div>)}</div><button className="primary-button" onClick={() => setAdding(!adding)} aria-expanded={adding}>+ Add demo person</button>{adding && <form className="person-form" onSubmit={e => { e.preventDefault(); const n = newName.trim(); if (!n) return; if (people.some(p => p.toLowerCase() === n.toLowerCase())) { setNotice('That name already exists.'); return } setPeople([...people, n]); setNewName(''); setAdding(false); setNotice(`${n} added to this demo. Face enrollment needs the backend.`) }}><label>Display name<input value={newName} onChange={e => setNewName(e.target.value)} maxLength={40} required autoComplete="off"/></label><button className="primary-button" type="submit">Add person</button></form>}<p className="demo-note" role="status">{notice || 'Demo profiles stay in this session. Live face enrollment is not connected yet.'}</p></>}
      {(panel === 'Item details' || panel === 'Event details') && !selected && <p className="empty-state">This record does not exist. Open inventory or history from the navigation.</p>}
      {panel === 'Item details' && selected && <><span className={`detail-object food-shape ${selected.kind}`} style={{'--food-color':selected.color}} aria-hidden="true"><span>{selected.name.split(' ')[0]}</span></span><h3 className="detail-title">{selected.name}</h3><dl><div><dt>Owner</dt><dd>{selected.owner}</dd></div><div><dt>Put in at</dt><dd>{selected.time}</dd></div><div><dt>Item ID</dt><dd>ITEM_{selected.id}</dd></div><div><dt>Status</dt><dd>Inside the fridge</dd></div></dl><button className="primary-button" onClick={() => navigate('Inventory')}>← All inventory</button></>}
      {panel === 'Event details' && selected && <><h3 className="detail-title">{selected.item}</h3><dl>{[['Action',selected.action],['Person',selected.person],['Owner',selected.owner],['Time',selected.time],['Confidence',selected.confidence],['Result',selected.result]].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className="demo-note">Low-confidence identities remain uncertain. All records shown are demo data.</p><button className="primary-button" onClick={() => navigate('Alerts')}>← Back to alerts</button></>}
    </Modal>}
  </div>
}
export default App