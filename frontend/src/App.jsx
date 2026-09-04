import { useEffect, useMemo, useState } from 'react'
import {
  createFieldEncounter,
  getEncounters,
  getMe,
  getMyRegionDex,
  getMyRegions,
  getRegionDex,
  getRegions,
  getRegionsAt,
  getSpecies,
  getTokens,
  importTaxon,
  login,
  logout,
  register,
  searchTaxa,
  syncEncounter,
} from './api.js'

const NAV = [
  ['home', '⌂', 'Home'],
  ['dex', '◫', 'Dex'],
  ['encounter', '＋', 'Find'],
  ['map', '⌖', 'Map'],
  ['profile', '◎', 'Profile'],
]

const tierLabels = {
  familiar: 'Familiar',
  notable: 'Notable',
  uncommon: 'Uncommon',
  elusive: 'Elusive',
  exceptional: 'Exceptional',
  unranked: 'Unranked',
  protected: 'Protected Encounter',
}

const prettyTier = (value) => tierLabels[value] || 'Unranked'
const pct = (value) => `${Number(value || 0).toFixed(1)}%`
const dateText = (value) => value ? new Date(value).toLocaleDateString() : '—'

function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('This browser does not support GPS location.'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({
        latitude: coords.latitude,
        longitude: coords.longitude,
        accuracy: coords.accuracy,
      }),
      (error) => reject(new Error(error.message || 'Could not get your location.')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  })
}

function ErrorBanner({ message, onClose }) {
  if (!message) return null
  return (
    <div className="banner error" role="alert">
      <span>{message}</span>
      {onClose && <button className="icon-button" onClick={onClose} aria-label="Dismiss">×</button>}
    </div>
  )
}

function Empty({ title, children }) {
  return <div className="empty"><strong>{title}</strong><p>{children}</p></div>
}

function ProgressRing({ value = 0, label }) {
  const safe = Math.max(0, Math.min(100, Number(value || 0)))
  return (
    <div className="progress-ring" style={{ '--progress': `${safe * 3.6}deg` }}>
      <div><strong>{Math.round(safe)}%</strong><span>{label}</span></div>
    </div>
  )
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'register') await register({ email, password, displayName })
      else await login({ email, password })
      await onAuthenticated()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-brand">
        <div className="brand-mark">S</div>
        <p className="eyebrow">FIELD TERMINAL // V1</p>
        <h1>SpriteDex</h1>
        <p>A living journal for finding the wild world around you.</p>
      </section>
      <form className="panel auth-panel" onSubmit={submit}>
        <div className="segmented">
          <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Sign in</button>
          <button type="button" className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Create account</button>
        </div>
        <ErrorBanner message={error} />
        {mode === 'register' && (
          <label>Explorer name<input required value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="name" /></label>
        )}
        <label>Email<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
        <label>Password<input required minLength="8" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} /></label>
        <button className="primary wide" disabled={busy}>{busy ? 'Opening field terminal…' : mode === 'login' ? 'Enter SpriteDex' : 'Begin exploring'}</button>
      </form>
    </main>
  )
}

function Home({ user, regions, myRegions, encounters, onNavigate, location, onLocate, locating }) {
  const activeRegion = location?.regions?.[0]
  const progress = activeRegion ? myRegions.find((item) => item.region_id === activeRegion.region_id) : myRegions[0]
  const recent = encounters.slice(0, 3)

  return (
    <div className="screen-stack">
      <header className="screen-header">
        <div><p className="eyebrow">GOOD FIELDING</p><h1>{user.display_name}</h1></div>
        <span className="status-dot">LIVE</span>
      </header>

      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">CURRENT REGION</p>
          <h2>{activeRegion?.name || progress?.name || 'Find your region'}</h2>
          <p className="muted">{location ? `GPS ±${Math.round(location.accuracy)} m` : 'Use your phone GPS to discover which SpriteDex Region you are standing in.'}</p>
          <div className="button-row">
            <button className="primary" onClick={() => onNavigate('encounter')}>＋ Find something</button>
            <button onClick={onLocate} disabled={locating}>{locating ? 'Locating…' : '⌖ Locate me'}</button>
          </div>
        </div>
        {progress && <ProgressRing value={progress.completion_percent} label={`${progress.discovered_species_count}/${progress.eligible_species_count}`} />}
      </section>

      <section className="metric-grid">
        <article className="metric"><strong>{new Set(encounters.map((e) => e.species_id)).size}</strong><span>species found</span></article>
        <article className="metric"><strong>{encounters.length}</strong><span>encounters</span></article>
        <article className="metric"><strong>{myRegions.length}</strong><span>regions</span></article>
      </section>

      <section>
        <div className="section-title"><h2>Recent encounters</h2><button className="text-button" onClick={() => onNavigate('map')}>View map</button></div>
        {recent.length ? <div className="card-list">{recent.map((item) => (
          <article className="list-card" key={item.encounter_id}>
            <div className="species-symbol">{(item.common_name || '?')[0]}</div>
            <div className="grow"><strong>{item.common_name || item.scientific_name || 'Unknown organism'}</strong><small>{dateText(item.encountered_at)}</small></div>
            <span className="chevron">›</span>
          </article>
        ))}</div> : <Empty title="Your journal is empty">Your first encounter will appear here.</Empty>}
      </section>

      {!regions.length && <div className="banner">Region catalogue is loading or unavailable.</div>}
    </div>
  )
}

function Dex({ regions, selectedRegionId, setSelectedRegionId, user, onSpecies }) {
  const [items, setItems] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const selected = regions.find((r) => r.region_id === Number(selectedRegionId))

  useEffect(() => {
    if (!selectedRegionId) return
    setLoading(true)
    setError('')
    ;(user ? getMyRegionDex(selectedRegionId) : getRegionDex(selectedRegionId))
      .then(setItems)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [selectedRegionId, user])

  const filtered = items.filter((item) => {
    const haystack = `${item.common_name || ''} ${item.scientific_name || ''}`.toLowerCase()
    return haystack.includes(query.toLowerCase())
  })
  const discovered = items.filter((item) => item.discovered).length

  return (
    <div className="screen-stack">
      <header className="screen-header"><div><p className="eyebrow">REGIONAL DEX</p><h1>{selected?.name || 'Choose a Region'}</h1></div></header>
      <select className="region-select" value={selectedRegionId || ''} onChange={(e) => setSelectedRegionId(Number(e.target.value))}>
        <option value="" disabled>Choose Region</option>
        {regions.map((region) => <option key={region.region_id} value={region.region_id}>{region.name}</option>)}
      </select>
      {user && items.length > 0 && <div className="dex-summary"><strong>{discovered} / {items.length}</strong><span>active species discovered</span></div>}
      <input className="search-box" type="search" placeholder="Search this Dex…" value={query} onChange={(e) => setQuery(e.target.value)} />
      <ErrorBanner message={error} />
      {loading ? <div className="loader">Reading the field guide…</div> : filtered.length ? (
        <div className="dex-grid">{filtered.map((item) => (
          <button className={`dex-card ${item.discovered ? 'discovered' : ''}`} key={item.species_id} onClick={() => onSpecies(item)}>
            <div className="dex-image">{item.discovered ? (item.common_name || '?')[0] : '?'}</div>
            <strong>{item.discovered || !user ? item.common_name || item.scientific_name : 'Undiscovered'}</strong>
            <span className={`tier tier-${item.public_tier || 'unranked'}`}>{prettyTier(item.public_tier)}</span>
          </button>
        ))}</div>
      ) : <Empty title="No active Dex entries">This Region may still be waiting for its seasonal biodiversity seed.</Empty>}
    </div>
  )
}

function Encounter({ onSaved, inatConnected }) {
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [photo, setPhoto] = useState(null)
  const [photoUrl, setPhotoUrl] = useState('')
  const [notes, setNotes] = useState('')
  const [location, setLocation] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [searching, setSearching] = useState(false)

  useEffect(() => () => { if (photoUrl) URL.revokeObjectURL(photoUrl) }, [photoUrl])

  async function findTaxa(event) {
    event?.preventDefault()
    if (search.trim().length < 2) return
    setSearching(true); setError('')
    try { setResults(await searchTaxa(search.trim())) }
    catch (err) { setError(err.message) }
    finally { setSearching(false) }
  }

  async function locate() {
    setError('')
    try { setLocation(await getPosition()) }
    catch (err) { setError(err.message) }
  }

  function choosePhoto(file) {
    setPhoto(file || null)
    if (photoUrl) URL.revokeObjectURL(photoUrl)
    setPhotoUrl(file ? URL.createObjectURL(file) : '')
  }

  async function save() {
    if (!selected) { setError('Choose an organism first.'); return }
    if (!location) { setError('Capture your GPS location first.'); return }
    setBusy(true); setError('')
    try {
      const localTaxon = selected.species_id ? selected : await importTaxon(selected.inat_taxon_id)
      const payload = await createFieldEncounter({
        speciesId: localTaxon.species_id,
        latitude: location.latitude,
        longitude: location.longitude,
        notes,
        photo,
        caption: photo ? 'SpriteDex field evidence' : '',
        syncInaturalist: Boolean(inatConnected),
      })
      setResult(payload)
      await onSaved(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const region = result.regions?.[0]
    return (
      <div className="screen-stack discovery-screen">
        <div className="discovery-burst">✦</div>
        <p className="eyebrow">{result.new_discovery ? 'NEW REGIONAL DISCOVERY' : 'ENCOUNTER LOGGED'}</p>
        <h1>{result.species?.common_name || result.species?.scientific_name}</h1>
        <p className="latin">{result.species?.scientific_name}</p>
        {photoUrl && <img className="discovery-photo" src={photoUrl} alt="Your encounter" />}
        {region ? <section className="panel discovery-panel">
          <div><span>Region</span><strong>{region.name}</strong></div>
          <div><span>Encounter tier</span><strong>{prettyTier(region.public_tier)}</strong></div>
          <div><span>Dex progress</span><strong>{region.discovered_species_count} / {region.eligible_species_count}</strong></div>
          <div><span>Points</span><strong>+{Number(region.points_awarded || 0)}</strong></div>
        </section> : <div className="banner">Saved outside any active SpriteDex Region.</div>}
        {result.inaturalist?.status === 'failed' && <div className="banner warning">Saved safely to SpriteDex. iNaturalist sync can be retried later.</div>}
        <button className="primary wide" onClick={() => { setResult(null); setSelected(null); setPhoto(null); setPhotoUrl(''); setNotes(''); setResults([]); setSearch('') }}>Find another</button>
      </div>
    )
  }

  return (
    <div className="screen-stack">
      <header className="screen-header"><div><p className="eyebrow">FIELD ENCOUNTER</p><h1>I found something</h1></div></header>
      <ErrorBanner message={error} onClose={() => setError('')} />
      <section className="capture-card">
        <label className="photo-picker">
          {photoUrl ? <img src={photoUrl} alt="Selected field evidence" /> : <div><span>◎</span><strong>Take or choose a photo</strong><small>JPEG, PNG, HEIC or HEIF</small></div>}
          <input type="file" accept="image/*" capture="environment" onChange={(e) => choosePhoto(e.target.files?.[0])} />
        </label>
      </section>

      <section className="panel compact-panel">
        <div className="section-title"><h2>1. What is it?</h2></div>
        {selected ? <article className="selected-taxon">
          {selected.default_photo_url ? <img src={selected.default_photo_url} alt="" /> : <div className="species-symbol">?</div>}
          <div className="grow"><strong>{selected.common_name}</strong><small>{selected.scientific_name}</small></div>
          <button className="text-button" onClick={() => setSelected(null)}>Change</button>
        </article> : <>
          <form className="inline-search" onSubmit={findTaxa}><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Robin, maple, monarch…" /><button disabled={searching}>{searching ? '…' : 'Search'}</button></form>
          <div className="taxon-results">{results.slice(0, 6).map((item) => <button key={item.inat_taxon_id} onClick={() => setSelected(item)}>
            {item.default_photo_url ? <img src={item.default_photo_url} alt="" /> : <div className="species-symbol">?</div>}
            <div><strong>{item.common_name}</strong><small>{item.scientific_name} · {item.rank}</small></div>
          </button>)}</div>
        </>}
      </section>

      <section className="panel compact-panel">
        <div className="section-title"><h2>2. Where are you?</h2><button className="text-button" onClick={locate}>Refresh GPS</button></div>
        {location ? <div className="gps-lock"><span className="gps-pulse" /><div><strong>GPS locked</strong><small>{location.latitude.toFixed(5)}, {location.longitude.toFixed(5)} · ±{Math.round(location.accuracy)} m</small></div></div> : <button className="wide" onClick={locate}>⌖ Capture GPS</button>}
      </section>

      <section className="panel compact-panel">
        <label>3. Field notes <span className="optional">optional</span><textarea rows="3" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Habitat, behaviour, anything memorable…" /></label>
      </section>

      <button className="primary wide big-action" onClick={save} disabled={busy || !selected || !location}>{busy ? 'Saving encounter…' : 'Save encounter'}</button>
      <p className="privacy-note">Your precise location stays in your private SpriteDex journal. Sensitive external locations are never reconstructed.</p>
    </div>
  )
}

function FieldMap({ encounters, location, onLocate }) {
  const points = location ? [...encounters.map((e) => ({ ...e, current: false })), { ...location, current: true }] : encounters.map((e) => ({ ...e, current: false }))
  const valid = points.filter((p) => Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude)))
  const bounds = useMemo(() => {
    if (!valid.length) return null
    const lats = valid.map((p) => Number(p.latitude)); const lons = valid.map((p) => Number(p.longitude))
    const minLat = Math.min(...lats); const maxLat = Math.max(...lats); const minLon = Math.min(...lons); const maxLon = Math.max(...lons)
    return { minLat, maxLat, minLon, maxLon, latSpan: Math.max(maxLat - minLat, 0.01), lonSpan: Math.max(maxLon - minLon, 0.01) }
  }, [encounters, location])

  const project = (point) => ({
    x: 30 + ((Number(point.longitude) - bounds.minLon) / bounds.lonSpan) * 340,
    y: 270 - ((Number(point.latitude) - bounds.minLat) / bounds.latSpan) * 240,
  })

  return (
    <div className="screen-stack">
      <header className="screen-header"><div><p className="eyebrow">PRIVATE FIELD MAP</p><h1>Your encounters</h1></div><button className="text-button" onClick={onLocate}>⌖ Me</button></header>
      <section className="field-map" aria-label="Private map of your encounter coordinates">
        <div className="map-grid" />
        {bounds ? <svg viewBox="0 0 400 300" role="img" aria-label="Relative field map">
          {valid.map((point, index) => { const pos = project(point); return <g key={point.current ? 'current' : point.encounter_id || index}>
            <circle cx={pos.x} cy={pos.y} r={point.current ? 9 : 6} className={point.current ? 'map-current' : 'map-point'} />
            {point.current && <circle cx={pos.x} cy={pos.y} r="17" className="map-current-ring" />}
          </g> })}
        </svg> : <Empty title="No coordinates yet">Log an encounter or capture your current GPS to populate your private field map.</Empty>}
        <div className="map-legend"><span><i className="legend-point" /> Encounter</span><span><i className="legend-current" /> You</span></div>
      </section>
      <div className="banner">This V1 map is intentionally private and basemap-free: your precise encounter coordinates are not sent to a third-party map provider.</div>
      <div className="card-list">{encounters.slice(0, 8).map((e) => <article className="list-card" key={e.encounter_id}><div className="species-symbol">{(e.common_name || '?')[0]}</div><div className="grow"><strong>{e.common_name || e.scientific_name}</strong><small>{Number(e.latitude).toFixed(4)}, {Number(e.longitude).toFixed(4)}</small></div></article>)}</div>
    </div>
  )
}

function SpeciesDetail({ item, encounters, onBack }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { getSpecies(item.species_id).then(setDetail).catch((err) => setError(err.message)) }, [item.species_id])
  const history = encounters.filter((e) => e.species_id === item.species_id)
  return (
    <div className="screen-stack">
      <button className="back-button" onClick={onBack}>‹ Regional Dex</button>
      <section className="species-hero">
        <div className="species-hero-mark">{(item.common_name || '?')[0]}</div>
        <p className="eyebrow">{item.discovered ? 'DISCOVERED' : 'REGIONAL SPECIES'}</p>
        <h1>{item.common_name || detail?.common_name}</h1>
        <p className="latin">{item.scientific_name || detail?.scientific_name}</p>
        <span className={`tier tier-${item.public_tier || 'unranked'}`}>{prettyTier(item.public_tier)}</span>
      </section>
      <ErrorBanner message={error} />
      <section className="panel detail-grid">
        <div><span>First found</span><strong>{dateText(item.first_observed_at)}</strong></div>
        <div><span>Encounters</span><strong>{item.encounter_count || history.length}</strong></div>
        <div><span>Regional points</span><strong>{Number(item.regional_points || 0)}</strong></div>
        <div><span>Group</span><strong>{detail?.category || detail?.iconic_taxon_name || '—'}</strong></div>
      </section>
      {detail?.description && <section className="panel"><h2>Field notes</h2><p>{detail.description}</p></section>}
      <section><h2>Your history</h2>{history.length ? <div className="card-list">{history.map((e) => <article className="list-card" key={e.encounter_id}><div className="grow"><strong>{dateText(e.encountered_at)}</strong><small>{e.notes || 'Field encounter'}</small></div><span>{e.photo_count ? '▣' : '•'}</span></article>)}</div> : <Empty title="No encounter history yet">Find this species to add it to your journal.</Empty>}</section>
    </div>
  )
}

function Profile({ user, myRegions, encounters, onLogout, inatStatus, onConnectInat, inatError }) {
  const speciesCount = new Set(encounters.map((e) => e.species_id)).size
  return (
    <div className="screen-stack">
      <header className="profile-header"><div className="avatar">{user.display_name.slice(0, 1).toUpperCase()}</div><div><p className="eyebrow">FIELD EXPLORER</p><h1>{user.display_name}</h1><p className="muted">{user.email}</p></div></header>
      <section className="metric-grid"><article className="metric"><strong>{speciesCount}</strong><span>species</span></article><article className="metric"><strong>{encounters.length}</strong><span>encounters</span></article><article className="metric"><strong>{myRegions.length}</strong><span>regions</span></article></section>
      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">SCIENCE CONNECTION</p><h2>iNaturalist</h2></div><span className={`connection-pill ${inatStatus?.connected ? 'connected' : ''}`}>{inatStatus?.connected ? 'Connected' : 'Not connected'}</span></div>
        {inatStatus?.connected ? <p>Connected as <strong>@{inatStatus.inat_login}</strong>. Eligible encounters can sync into your own iNaturalist account.</p> : <><p className="muted">Connect your own account so SpriteDex encounters can become community biodiversity observations.</p><button className="primary" onClick={onConnectInat}>Connect iNaturalist</button></>}
        {inatError && <p className="error-text">{inatError}</p>}
      </section>
      <section><h2>Regional progress</h2>{myRegions.length ? <div className="card-list">{myRegions.map((r) => <article className="list-card" key={r.region_id}><div className="grow"><strong>{r.name}</strong><small>{r.discovered_species_count} / {r.eligible_species_count} species</small></div><span className="score">{pct(r.completion_percent)}</span></article>)}</div> : <Empty title="No Regions explored">Your first Regional Dex will appear after an in-Region encounter.</Empty>}</section>
      <button className="danger wide" onClick={onLogout}>Sign out</button>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(null)
  const [screen, setScreen] = useState('home')
  const [booting, setBooting] = useState(true)
  const [error, setError] = useState('')
  const [regions, setRegions] = useState([])
  const [myRegions, setMyRegions] = useState([])
  const [encounters, setEncounters] = useState([])
  const [selectedRegionId, setSelectedRegionId] = useState(null)
  const [selectedSpecies, setSelectedSpecies] = useState(null)
  const [location, setLocation] = useState(null)
  const [locating, setLocating] = useState(false)
  const [inatStatus, setInatStatus] = useState({ connected: false })
  const [inatError, setInatError] = useState('')

  async function refreshPublic() {
    const list = await getRegions()
    setRegions(list)
    setSelectedRegionId((current) => current || list.find((r) => r.slug === 'ganaraska-forest')?.region_id || list[0]?.region_id || null)
  }

  async function refreshPrivate() {
    const [regionProgress, journal] = await Promise.all([getMyRegions(), getEncounters(200)])
    setMyRegions(regionProgress)
    setEncounters(journal)
    try {
      const status = await (await import('./api.js')).apiFetch('/api/inaturalist/status')
      setInatStatus(status)
    } catch (err) {
      setInatError(err.message)
    }
  }

  async function bootstrap() {
    setBooting(true); setError('')
    try {
      await refreshPublic()
      if (getTokens()) {
        const current = await getMe()
        setUser(current)
        await refreshPrivate()
      }
    } catch (err) {
      if (err.status === 401) setUser(null)
      else setError(err.message)
    } finally { setBooting(false) }
  }

  useEffect(() => { bootstrap() }, [])

  async function authenticated() {
    const current = await getMe(); setUser(current); await refreshPublic(); await refreshPrivate(); setScreen('home')
  }

  async function doLogout() {
    await logout(); setUser(null); setMyRegions([]); setEncounters([]); setScreen('home')
  }

  async function locate() {
    setLocating(true); setError('')
    try {
      const pos = await getPosition()
      const matched = await getRegionsAt(pos.latitude, pos.longitude)
      const full = { ...pos, regions: matched }
      setLocation(full)
      if (matched[0]) setSelectedRegionId(matched[0].region_id)
      return full
    } catch (err) { setError(err.message); return null }
    finally { setLocating(false) }
  }

  async function encounterSaved() { await refreshPrivate() }

  async function connectInat() {
    setInatError('')
    try {
      const { apiFetch } = await import('./api.js')
      const data = await apiFetch('/api/inaturalist/connect')
      window.location.assign(data.authorization_url)
    } catch (err) { setInatError(err.message) }
  }

  if (booting) return <div className="splash"><div className="brand-mark">S</div><strong>SpriteDex</strong><span>Waking the field terminal…</span></div>
  if (!user) return <><ErrorBanner message={error} /><AuthScreen onAuthenticated={authenticated} /></>

  let content
  if (selectedSpecies) content = <SpeciesDetail item={selectedSpecies} encounters={encounters} onBack={() => setSelectedSpecies(null)} />
  else if (screen === 'home') content = <Home user={user} regions={regions} myRegions={myRegions} encounters={encounters} onNavigate={setScreen} location={location} onLocate={locate} locating={locating} />
  else if (screen === 'dex') content = <Dex regions={regions} selectedRegionId={selectedRegionId} setSelectedRegionId={setSelectedRegionId} user={user} onSpecies={setSelectedSpecies} />
  else if (screen === 'encounter') content = <Encounter onSaved={encounterSaved} inatConnected={inatStatus?.connected} />
  else if (screen === 'map') content = <FieldMap encounters={encounters} location={location} onLocate={locate} />
  else content = <Profile user={user} myRegions={myRegions} encounters={encounters} onLogout={doLogout} inatStatus={inatStatus} onConnectInat={connectInat} inatError={inatError} />

  return (
    <div className="app-shell">
      <main className="app-main"><ErrorBanner message={error} onClose={() => setError('')} />{content}</main>
      {!selectedSpecies && <nav className="bottom-nav" aria-label="SpriteDex navigation">{NAV.map(([key, icon, label]) => <button key={key} className={screen === key ? 'active' : ''} onClick={() => setScreen(key)}><span>{icon}</span><small>{label}</small></button>)}</nav>}
    </div>
  )
}
