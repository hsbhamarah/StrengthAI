import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Athlete = { athlete_id: string; display_name: string; goal: string | null; status: string };
type Source = { source_id: string; display_name: string };
type Metric = { key: string; value: number | null; unit: string | null; sample_count: number; evidence_ids: string[]; method_version: string; state: string };
type SetRow = { id: string; set_type: string; side: string; target_reps: number | null; target_reps_min: number | null; target_reps_max: number | null; target_rpe: number | null; target_rpe_min: number | null; target_rpe_max: number | null; status: string | null; reps: number | null; load_kg: number | null; actual_rpe: number | null; source: { sheet: string; cell_range: string } | null };
type Issue = { severity: 'warning' | 'blocking'; code: string; location: string; message: string };
type Preview = { import_id: string; source_snapshot_hash: string; layout_fingerprint: string; sheets: string[]; sample_rows: { sheet: string; row: number; cells: Record<string, unknown> }[]; issues: Issue[]; correction_cells: { location: string; raw_value: string }[]; proposed_mapping: Record<string, unknown> | null };
type DraftPreview = { layout_fingerprint: string; row_count: number; blocking_count: number; can_approve: boolean; issues_truncated: boolean; exercise_labels: string[]; issues: Issue[]; correction_cells: { location: string; field: string; raw_value: string }[]; valid_sample_rows: { source: string; block: string; week: string; session: string; exercise: string; set_index: number; side: string; values: Record<string, unknown> }[] };
type View = 'overview' | 'training' | 'imports' | 'backup';

let csrf = sessionStorage.getItem('strengthos_csrf') || '';

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong';
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && csrf) {
    sessionStorage.removeItem('strengthos_csrf');
    window.location.replace('/sign-in');
  }
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`);
  }
  return body as T;
}

const format = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
const target = (value: number | null, min: number | null, max: number | null) => min == null ? format(value) : `${format(min)}–${format(max)}`;
const labels: Record<string, string> = {
  completed_sets: 'Completed sets', failed_sets: 'Failed sets', completion_rate: 'Completion rate',
  volume_load_kg: 'Volume load', mean_rpe_deviation: 'Mean RPE deviation', e1rm_kg: 'Estimated 1RM',
};
const mappingFields = ['block', 'week', 'session', 'exercise_label', 'set_index', 'set_type', 'target_reps', 'target_load', 'target_rpe', 'target_rir', 'actual_reps', 'actual_load', 'actual_rpe', 'actual_rir', 'actual_status'];

function SetTable({ rows, compact = false }: { rows: SetRow[]; compact?: boolean }) {
  if (!rows.length) return <div className="empty-table">No sets to show.</div>;
  return <div className="table-wrap"><table>
    <thead><tr className="group-head"><th colSpan={2} scope="colgroup">Workbook</th><th colSpan={2} scope="colgroup">Prescription</th><th colSpan={compact ? 3 : 4} scope="colgroup">Actual performance</th></tr><tr><th>Source cell</th><th>Set</th><th>Target reps</th><th>Target RPE</th><th>Status</th><th>Actual reps</th><th>Load</th>{!compact && <th>Actual RPE</th>}</tr></thead>
    <tbody>{rows.map(row => <tr key={row.id}>
      <td><strong>{row.source?.sheet || 'Source unknown'}</strong><small>{row.source?.cell_range || 'No cell reference'}</small></td>
      <td><strong>{row.set_type}</strong><small>{row.side}</small></td>
      <td>{target(row.target_reps, row.target_reps_min, row.target_reps_max)}</td>
      <td>{target(row.target_rpe, row.target_rpe_min, row.target_rpe_max)}</td>
      <td><span className={`status ${row.status || 'unreported'}`}>{row.status || 'unreported'}</span></td>
      <td>{format(row.reps)}</td><td>{format(row.load_kg)} <small>kg</small></td>
      {!compact && <td>{format(row.actual_rpe)}</td>}
    </tr>)}</tbody>
  </table></div>;
}

function BackupPanel() {
  const [phrase, setPhrase] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (phrase !== confirmation) { setMessage('Passphrases differ. Enter them again.'); return; }
    setPending(true); setMessage('');
    try {
      const picker = (window as Window & {showSaveFilePicker?: (options: {suggestedName: string}) => Promise<FileSystemFileHandle>}).showSaveFilePicker;
      const filename = 'StrengthOS-' + new Date().toISOString().slice(0, 10) + '.strengthbackup';
      const handle = picker ? await picker.call(window, {suggestedName: filename}) : null;
      const response = await fetch('/api/v1/backups', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify({passphrase: phrase})});
      if (response.status === 401) { sessionStorage.removeItem('strengthos_csrf'); window.location.replace('/sign-in'); }
      if (!response.ok) throw new Error('Backup failed. Check your session and try again.');
      const blob = await response.blob();
      if (handle) {
        const file = await handle.createWritable(); await file.write(blob); await file.close();
      } else {
        const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename; link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 30000);
      }
      setMessage(handle ? 'Encrypted backup saved.' : 'Encrypted backup sent to your browser downloads.');
      setPhrase(''); setConfirmation('');
    } catch (err) { setMessage(err instanceof DOMException && err.name === 'AbortError' ? 'Save cancelled.' : errorText(err)); }
    finally { setPending(false); }
  }
  return <section className="backup-panel"><p className="eyebrow">WORKSPACE</p><h1>Encrypted backup</h1><p>Save training records, mapping history and source workbooks together. Keep the recovery passphrase somewhere you can reach if this computer is lost.</p>
    <form onSubmit={save}><label>Recovery passphrase<input type="password" autoComplete="new-password" minLength={16} maxLength={1024} required value={phrase} onChange={e => setPhrase(e.target.value)} /></label>
    <label>Confirm passphrase<input type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label>
    <small>Use at least 16 characters.</small><button disabled={pending}>{pending ? 'Preparing backup?' : 'Save encrypted backup'}</button></form><p role="status">{message}</p></section>;
}

function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(csrf));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [signupAvailable, setSignupAvailable] = useState<boolean | null>(null);
  const [needsEmailSetup, setNeedsEmailSetup] = useState(false);
  const [athletes, setAthletes] = useState<Athlete[]>([]);
  const [selected, setSelected] = useState('');
  const [view, setView] = useState<View>('overview');
  const [newName, setNewName] = useState('');
  const [newGoal, setNewGoal] = useState('');
  const [adding, setAdding] = useState(false);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const [sets, setSets] = useState<SetRow[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [sheet, setSheet] = useState('');
  const [showSamples, setShowSamples] = useState(false);
  const [mapping, setMapping] = useState('');
  const [aliasSource, setAliasSource] = useState('');
  const [aliasTarget, setAliasTarget] = useState('');
  const [mappingId, setMappingId] = useState('');
  const [draft, setDraft] = useState<DraftPreview | null>(null);
  const [draftStale, setDraftStale] = useState(false);
  const [issuePage, setIssuePage] = useState(0);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [metricKey, setMetricKey] = useState('');
  const metricFilter = metrics.find(metric => metric.key === metricKey);
  const evidence = useMemo(() => new Set(metricFilter?.evidence_ids), [metricFilter]);
  const [status, setStatus] = useState('all');
  const signUpPage = window.location.pathname === '/sign-up';

  const athlete = athletes.find(item => item.athlete_id === selected);
  const samples = preview?.sample_rows.filter(row => row.sheet === sheet) || [];
  const filteredSets = useMemo(() => sets.filter(row => {
    const matchStatus = status === 'all' || (row.status || 'unreported') === status;
    const text = `${row.source?.sheet || ''} ${row.source?.cell_range || ''} ${row.set_type} ${row.side}`.toLowerCase();
    return (!metricFilter || evidence.has(row.id)) && matchStatus && text.includes(search.toLowerCase().trim());
  }), [sets, search, status, evidence, metricFilter]);

  let parsed: Record<string, any> | null = null;
  try {
    const value = JSON.parse(mapping);
    if (value && typeof value === 'object' && !Array.isArray(value)) parsed = value;
  } catch { /* The editor remains available for correction. */ }
  const unresolved = (draft?.correction_cells || preview?.correction_cells || []).filter(cell => parsed?.cell_overrides?.[cell.location] === undefined && parsed?.actual_status_overrides?.[cell.location] === undefined);
  const missingBlock = parsed?.layout === 'wide_week_grid' && (parsed.sheet_mappings || []).some((group: Record<string, any>) => !String(group.block_label || parsed.block_label || '').trim());
  const missingAliases = parsed?.layout === 'wide_week_grid' && !Object.values(parsed.exercise_aliases || {}).some(Boolean);
  const canApprove = Boolean(preview && parsed && draft?.can_approve && !draftStale && !missingBlock && !missingAliases && !unresolved.length && !busy);

  function report(err: unknown) { setNotice(''); setError(errorText(err)); }
  function clearSession() {
    csrf = ''; sessionStorage.removeItem('strengthos_csrf'); setLoggedIn(false); setSelected(''); setAthletes([]);
    window.history.replaceState(null, '', '/sign-in');
  }
  async function loadAthletes() {
    const result = await api<{ items: Athlete[] }>('/athletes');
    setAthletes(result.items);
    setSelected(current => result.items.some(item => item.athlete_id === current) ? current : result.items[0]?.athlete_id || '');
  }
  useEffect(() => {
    if (!loggedIn) return;
    loadAthletes().catch(err => {
      if (errorText(err).includes('Coach login required') || errorText(err).includes('(401)')) clearSession();
      else report(err);
    });
  }, [loggedIn]);
  useEffect(() => {
    if (loggedIn) return;
    api<{ signup_available: boolean; needs_email_setup: boolean }>('/auth/setup-status')
      .then(result => { setSignupAvailable(result.signup_available); setNeedsEmailSetup(result.needs_email_setup); })
      .catch(report);
  }, [loggedIn]);
  useEffect(() => {
    setMetricKey(''); setMetrics([]); setSets([]); setSources([]); setSourceId(''); setFile(null);
    setPreview(null); setMapping(''); setMappingId(''); setError(''); setNotice('');
    if (!selected) return;
    let active = true;
    setLoadingData(true);
    Promise.all([
      api<{ metrics: Metric[]; sets: SetRow[] }>(`/athletes/${selected}/analytics`),
      api<{ items: Source[] }>(`/athletes/${selected}/sources`),
    ]).then(([analytics, sourceList]) => {
      if (!active) return;
      setMetrics(analytics.metrics); setSets(analytics.sets); setSources(sourceList.items);
    }).catch(err => { if (active) report(err); }).finally(() => { if (active) setLoadingData(false); });
    return () => { active = false; };
  }, [selected]);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setBusy('login'); setError('');
    try {
      const result = await api<{ csrf_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) });
      csrf = result.csrf_token; sessionStorage.setItem('strengthos_csrf', csrf);
      setPassword(''); setLoggedIn(true); window.history.replaceState(null, '', '/');
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  async function signup(event: React.FormEvent) {
    event.preventDefault(); setError('');
    if (password !== confirmPassword) { setError('Passwords do not match.'); return; }
    setBusy('signup');
    try {
      await api('/auth/signup', { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) });
      setPassword(''); setConfirmPassword('');
      window.location.assign('/sign-in?created=1');
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); clearSession(); }
    catch (err) { report(err); }
  }
  async function addAthlete(event: React.FormEvent) {
    event.preventDefault(); setBusy('athlete'); setError('');
    try {
      const created = await api<Athlete>('/athletes', { method: 'POST', body: JSON.stringify({ display_name: newName.trim(), goal: newGoal.trim() || null }) });
      await loadAthletes(); setSelected(created.athlete_id);
      setNewName(''); setNewGoal(''); setAdding(false); setNotice(`${created.display_name} added`);
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  function changeMapping(value: string) { setMapping(value); setMappingId(''); setDraftStale(true); setNotice(''); }
  function updateMapping(edit: (value: Record<string, any>) => void) {
    if (!parsed) return;
    const next = structuredClone(parsed); edit(next); changeMapping(JSON.stringify(next, null, 2));
  }
  async function upload() {
    if (!selected || !file) return;
    setBusy('upload'); setError(''); setNotice('');
    try {
      const body = new FormData(); body.append('athlete_id', selected); body.append('file', file);
      if (sourceId) body.append('source_id', sourceId);
      const uploaded = await api<{ import_id: string; source_id: string }>('/imports/excel', { method: 'POST', body });
      const next = await api<Preview>(`/imports/${uploaded.import_id}/preview`);
      const sourceList = await api<{ items: Source[] }>(`/athletes/${selected}/sources`);
      setSources(sourceList.items); setSourceId(uploaded.source_id); setPreview(next); setDraft(null); setDraftStale(false); setIssuePage(0);
      setSheet(next.sheets[0] || ''); setShowSamples(false);
      setMapping(JSON.stringify(next.proposed_mapping || { sheet: next.sheets[0], header_row: 1, columns: {}, load_unit: 'kg', exercise_aliases: {} }, null, 2));
      setMappingId(''); setNotice('Workbook uploaded. Review the source sample and mapping.');
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  async function previewMapping() {
    if (!preview || !parsed) return;
    setBusy('mapping-preview'); setError(''); setNotice('');
    try {
      const result = await api<DraftPreview>(`/imports/${preview.import_id}/mapping-preview`, { method: 'POST', body: JSON.stringify({ mapping: parsed }) });
      setDraft(result); setDraftStale(false); setIssuePage(0);
      setNotice(result.can_approve ? `${result.row_count} mapped sets are ready for approval.` : `${result.blocking_count} issues need review before approval.`);
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  async function approve() {
    if (!preview || !canApprove) return;
    setBusy('approve'); setError(''); setNotice('');
    try {
      const id = crypto.randomUUID();
      await api(`/mappings/${id}`, { method: 'PUT', body: JSON.stringify({ import_id: preview.import_id, layout_fingerprint: draft?.layout_fingerprint, mapping: parsed }) });
      setMappingId(id); setNotice('Mapping approved. You can now commit this snapshot.');
    } catch (err) { report(err); } finally { setBusy(''); }
  }
  async function commit() {
    if (!preview || !mappingId || !selected) return;
    setBusy('commit'); setError(''); setNotice('');
    try {
      const result = await api<{ changed_records: number }>(`/imports/${preview.import_id}/commit`, { method: 'POST', body: JSON.stringify({ mapping_id: mappingId, acknowledged_snapshot_hash: preview.source_snapshot_hash }) });
      const analytics = await api<{ metrics: Metric[]; sets: SetRow[] }>(`/athletes/${selected}/analytics`);
      setMetrics(analytics.metrics); setSets(analytics.sets); setMappingId('');
      setNotice(`${result.changed_records} set records committed. Dashboard updated.`);
    } catch (err) { report(err); } finally { setBusy(''); }
  }

  if (!loggedIn) return <div className="auth-page">
    <div className="auth-art"><div className="studio-wordmark">StrengthOS<span> / AI</span></div><div className="barbell" aria-hidden="true"><i/><i/><i/><b/><i/><i/><i/></div><div><p className="eyebrow">COACH WORKSPACE</p><p className="auth-headline">Training studio</p></div></div>
    <main className="auth-panel"><div className="auth-card"><p className="eyebrow">COACH WORKSPACE</p><h1>{signUpPage ? 'Create coach account' : 'Sign in'}</h1><p>{signUpPage ? 'One coach account for this local workspace.' : 'Use your coach email and password to open this local workspace.'}</p>
      {!signUpPage && <>
        {window.location.search.includes('created=1') && <p className="alert success" role="status">Account created. Sign in to continue.</p>}
        <form onSubmit={login}><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" inputMode="email" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required autoFocus /><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /><button type="submit" disabled={busy === 'login'}>{busy === 'login' ? 'Signing in…' : 'Sign in'}</button></form>
        {signupAvailable && <p className="auth-switch">First time here? <a href="/sign-up">Create coach account</a></p>}
      </>}
      {signUpPage && (signupAvailable === null ? <p role="status">Checking local account…</p> : signupAvailable ? <form onSubmit={signup}><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" inputMode="email" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required autoFocus /><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} minLength={12} maxLength={1024} required /><p className="auth-hint">Use at least 12 characters.</p><label htmlFor="confirm-password">Confirm password</label><input id="confirm-password" name="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} required /><button type="submit" disabled={busy === 'signup'}>{busy === 'signup' ? 'Creating account…' : 'Create account'}</button></form> : <p className="auth-hint">A coach account already exists on this computer.</p>)}
      {signUpPage && <p className="auth-switch"><a href="/sign-in">Back to sign in</a></p>}
      {needsEmailSetup && <p className="auth-hint">This account needs an email. Run <code>python -m strengthos.setup</code> in the project folder and confirm the existing password.</p>}
      {error && <p className="alert error" role="alert">{error}</p>}<small>Runs on this computer. Athlete access is managed by the coach.</small>
    </div></main>
  </div>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="sidebar-brand"><span className="brand-mark small">S<span>O</span></span><span><strong>StrengthOS</strong><small>COACH WORKSPACE</small></span></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav className="primary-nav" aria-label="Main navigation">
        {([['overview', 'Overview'], ['training', 'Training'], ['imports', 'Import data'], ['backup', 'Backup']] as const).map(([key, label]) => <button key={key} type="button" aria-current={view === key ? 'page' : undefined} className={view === key ? 'active' : ''} onClick={() => setView(key)}><span className="nav-icon" aria-hidden="true">{key === 'overview' ? '▦' : key === 'training' ? '▤' : '↥'}</span>{label}</button>)}
      </nav>
      <div className="sidebar-section-heading"><span>ATHLETES</span><button type="button" aria-label="Add athlete" title="Add athlete" onClick={() => setAdding(value => !value)}>+</button></div>
      <nav className="athlete-nav" aria-label="Athletes">{athletes.map(item => <button key={item.athlete_id} type="button" disabled={Boolean(busy)} className={selected === item.athlete_id ? 'active' : ''} onClick={() => setSelected(item.athlete_id)}><span className="avatar">{item.display_name.trim().slice(0, 1).toUpperCase()}</span><span className="athlete-name">{item.display_name}</span></button>)}</nav>
      {adding && <form className="add-athlete" onSubmit={addAthlete}><label htmlFor="new-name">Athlete name</label><input id="new-name" value={newName} onChange={event => setNewName(event.target.value)} maxLength={120} required /><label htmlFor="new-goal">Goal (optional)</label><textarea id="new-goal" value={newGoal} onChange={event => setNewGoal(event.target.value)} maxLength={1000} rows={2} /><div className="form-actions"><button disabled={busy === 'athlete'}>Add</button><button type="button" className="text-button" onClick={() => setAdding(false)}>Cancel</button></div></form>}
      <div className="sidebar-footer"><span className="online-dot" /> Local workspace <button type="button" onClick={logout}>Sign out</button></div>
    </aside>
    <div className="main-column">
      <header className="topbar"><div><span className="topbar-kicker">COACH / {view.toUpperCase()}</span><span className="divider" />{athlete?.display_name || 'No athlete selected'}</div><span className="local-pill"><span className="online-dot" /> LOCAL</span></header>
      <main className="content">
        {error && <div className="alert error" role="alert">{error}<button type="button" aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
        {notice && <div className="alert success" role="status">{notice}<button type="button" aria-label="Dismiss notice" onClick={() => setNotice('')}>×</button></div>}
        {view === 'backup' ? <BackupPanel /> : !athlete ? <section className="empty-workspace"><div className="empty-symbol">＋</div><h1>Start with an athlete.</h1><p>Add an athlete to organize training data and imports.</p><button type="button" onClick={() => setAdding(true)}>Add athlete</button></section> : <>
          {loadingData && <p role="status">Loading athlete records?</p>}
          {view === 'overview' && <>
            <div className="page-heading"><div><p className="eyebrow">ATHLETE OVERVIEW</p><h1>{athlete.display_name}</h1><p>{athlete.goal || 'Training summary and current data.'}</p></div><button type="button" className="outline-button" onClick={() => setView('imports')}>↥ Import workbook</button></div>
            <div className="summary-strip"><span><span className="online-dot" /> ACTIVE ATHLETE</span><span>{sets.length} tracked sets</span><span>{sources.length} workbook {sources.length === 1 ? 'source' : 'sources'}</span></div>
            {metrics.length ? <div className="metric-grid">{metrics.map(metric => <article className="metric-card" key={metric.key}><span>{labels[metric.key] || metric.key.replaceAll('_', ' ')}</span><strong>{metric.value == null ? '—' : metric.key === 'completion_rate' ? `${format(metric.value * 100)}%` : format(metric.value)}</strong><small>{metric.unit && metric.key !== 'completion_rate' ? `${metric.unit} · ` : ''}{metric.sample_count} source {metric.sample_count === 1 ? 'set' : 'sets'}</small>{metric.sample_count > 0 && <button className="metric-link" onClick={() => { setMetricKey(metric.key); setStatus('all'); setSearch(''); setView('training'); }} aria-label={'View source sets for ' + labels[metric.key]}>View source sets</button>}</article>)}</div> : loadingData ? null : <section className="empty-card"><h2>No training data yet</h2><p>Import an Excel workbook to see sets and calculated metrics.</p><button type="button" onClick={() => setView('imports')}>Import workbook</button></section>}
            <section className="panel"><div className="section-title"><div><p className="eyebrow">TRAINING LOG</p><h2>Sets and source evidence</h2></div><button type="button" className="text-button" onClick={() => setView('training')}>View all sets →</button></div><SetTable rows={sets.slice(0, 6)} compact /></section>
          </>}
          {view === 'training' && <>
            <div className="page-heading"><div><p className="eyebrow">TRAINING DATA</p><h1>Training log</h1><p>Prescriptions and actuals stay separate. Source cells trace each imported set.</p></div><span className="count-pill">{sets.length} sets</span></div>
            <section className="panel">{metricFilter && <p>Source sets for {labels[metricFilter.key]} <button type="button" className="text-button" onClick={() => setMetricKey('')}>Show all sets</button></p>}<div className="table-tools"><label>Search source or set<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Sheet, cell, type, side" /></label><label>Status<select value={status} onChange={event => setStatus(event.target.value)}><option value="all">All statuses</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="unreported">Unreported</option></select></label></div><SetTable rows={filteredSets} /></section>
          </>}
          {view === 'imports' && <>
            <div className="page-heading"><div><p className="eyebrow">DATA INGESTION</p><h1>Import a workbook</h1><p>Upload, review the mapping, then approve and commit the snapshot.</p></div><span className="count-pill">Excel .xlsx</span></div>
            <div className="import-steps"><span className="current"><b>1</b> Upload</span><span className={preview ? 'current' : ''}><b>2</b> Review mapping</span><span className={mappingId ? 'current' : ''}><b>3</b> Commit</span></div>
            <section className="panel"><div className="section-title"><div><p className="eyebrow">SOURCE</p><h2>Choose a workbook</h2></div></div><div className="two-col">
              <label>Workbook source<select value={sourceId} onChange={event => { setSourceId(event.target.value); setPreview(null); setMappingId(''); }}><option value="">New source</option>{sources.map(source => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select><small>Select an existing source for a corrected workbook.</small></label>
              <label>Excel file<input type="file" accept=".xlsx" onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null); setMappingId(''); }} /><small>Local .xlsx file, up to 10 MB.</small></label>
            </div><button type="button" disabled={!file || Boolean(busy)} onClick={upload}>{busy === 'upload' ? 'Reading workbook…' : 'Preview workbook'}</button></section>
            {preview && <>
              <section className="panel"><div className="section-title"><div><p className="eyebrow">WORKBOOK SNAPSHOT</p><h2>Review source data</h2></div><span className="hash-pill" title={preview.source_snapshot_hash}>SHA-256 {preview.source_snapshot_hash.slice(0, 12)}…</span></div>
                <p className="helper">Check the source cells below before approving their mapping.</p>
                <div className="sheet-tabs" role="group" aria-label="Workbook sheet">{preview.sheets.map(name => <button type="button" key={name} className={sheet === name ? 'active' : ''} onClick={() => { setSheet(name); setShowSamples(false); }}>{name}</button>)}</div>
                <div className="sample-list">{(showSamples ? samples : samples.slice(0, 5)).map(row => <div className="sample-row" key={`${row.sheet}-${row.row}`}><strong>Row {row.row}</strong><code>{Object.entries(row.cells).map(([cell, value]) => `${cell}: ${String(value)}`).join('  ·  ') || 'Empty row'}</code></div>)}</div>
                {samples.length > 5 && <button type="button" className="text-button" onClick={() => setShowSamples(value => !value)}>{showSamples ? 'Show fewer rows' : `Show all ${samples.length} sample rows`}</button>}
                {preview.issues.length > 0 && <div className="issue-list"><h3>Import notes</h3>{preview.issues.map((issue, index) => <div className={`issue ${issue.severity}`} key={`${issue.code}-${index}`}><b>{issue.severity === 'blocking' ? '!' : 'i'}</b><p><strong>{issue.severity === 'blocking' ? 'Needs correction' : 'Review'}</strong> {issue.message}</p></div>)}</div>}
              </section>
              <section className="panel"><div className="section-title"><div><p className="eyebrow">COACH APPROVAL</p><h2>Mapping</h2></div><span className="count-pill">{mappingId ? 'Approved' : 'Not approved'}</span></div><p className="helper">Any mapping change clears approval. Source values are never changed by these controls.</p>
                {parsed && <div className="two-col"><label>Workbook layout<select value={parsed.layout || 'row_per_set'} onChange={event => updateMapping(next => { if (event.target.value === 'wide_week_grid') Object.assign(next, {layout: 'wide_week_grid', schema_version: 2, sheet_mappings: [{sheet: preview.sheets[0], block_label: '', week_header_row: 1, header_row: 2, session_column: 'A', exercise_column: 'B', set_index_mode: 'row_order', week_columns: []}], cell_overrides: {}, actual_status_overrides: {}}); else Object.assign(next, {layout: 'row_per_set', sheet: preview.sheets[0], header_row: 1, columns: {}, cell_overrides: {}, actual_status_overrides: {}}); })}><option value="wide_week_grid">Repeated week grid</option><option value="row_per_set">One row per set</option></select></label></div>}
                {parsed?.layout === 'wide_week_grid' && <>
                  <div className="two-col"><label>Load unit<select value={parsed.load_unit || 'kg'} onChange={event => updateMapping(next => { next.load_unit = event.target.value; })}><option value="kg">Kilograms</option><option value="lb">Pounds</option></select></label></div>
                  <div className="mapping-summary"><h3>Training sheets</h3><p className="helper">Likely grids are selected. Include only tabs you want to import.</p><div className="sheet-choices">{preview.sheets.map(name => <label key={name}><input type="checkbox" checked={(parsed.sheet_mappings || []).some((group: {sheet: string}) => group.sheet === name)} onChange={event => updateMapping(next => { if (event.target.checked) next.sheet_mappings.push({sheet: name, block_label: '', week_header_row: 1, header_row: 2, session_column: 'A', exercise_column: 'B', set_index_mode: 'row_order', week_columns: []}); else next.sheet_mappings = next.sheet_mappings.filter((group: {sheet: string}) => group.sheet !== name); })} />{name}</label>)}</div></div>
                  {(parsed.sheet_mappings || []).map((group: {sheet: string; block_label?: string; week_header_row?: number; header_row?: number; session_column?: string; exercise_column?: string; set_index_mode?: string; week_columns?: string[]}, index: number) => <fieldset className="wizard-sheet" key={group.sheet}><legend>{group.sheet}</legend><div className="two-col"><label>Training block label<input value={group.block_label || ''} onChange={event => updateMapping(next => { next.sheet_mappings[index].block_label = event.target.value; })} placeholder="e.g. Block 1" /></label><label>Week header row<input type="number" min="1" value={group.week_header_row || 1} onChange={event => updateMapping(next => { next.sheet_mappings[index].week_header_row = Number(event.target.value); })} /></label><label>Set header row<input type="number" min="1" value={group.header_row || 2} onChange={event => updateMapping(next => { next.sheet_mappings[index].header_row = Number(event.target.value); })} /></label><label>Week start columns<input defaultValue={(group.week_columns || []).join(', ')} onBlur={event => updateMapping(next => { next.sheet_mappings[index].week_columns = event.target.value.toUpperCase().split(/[\s,]+/).filter(Boolean); })} placeholder="C, I, O" /></label><label>Day column<input value={group.session_column || 'A'} maxLength={2} onChange={event => updateMapping(next => { next.sheet_mappings[index].session_column = event.target.value.toUpperCase(); })} /></label><label>Exercise column<input value={group.exercise_column || 'B'} maxLength={2} onChange={event => updateMapping(next => { next.sheet_mappings[index].exercise_column = event.target.value.toUpperCase(); })} /></label><label>Set labels<select value={group.set_index_mode || 'cell_index'} onChange={event => updateMapping(next => { next.sheet_mappings[index].set_index_mode = event.target.value; })}><option value="row_order">One set per row (numbered by row order)</option><option value="cell_index">Cell gives set index</option></select></label></div></fieldset>)}
                </>}
                {parsed && parsed.layout !== 'wide_week_grid' && <div className="mapping-summary"><h3>Row-per-set columns</h3><div className="two-col"><label>Training sheet<select value={parsed.sheet || ''} onChange={event => updateMapping(next => { next.sheet = event.target.value; })}>{preview.sheets.map(name => <option key={name} value={name}>{name}</option>)}</select></label><label>Header row<input type="number" min="1" value={parsed.header_row || 1} onChange={event => updateMapping(next => { next.header_row = Number(event.target.value); })} /></label><label>Load unit<select value={parsed.load_unit || 'kg'} onChange={event => updateMapping(next => { next.load_unit = event.target.value; })}><option value="kg">Kilograms</option><option value="lb">Pounds</option></select></label></div><div className="two-col">{mappingFields.map(field => <label key={field}>{field.replaceAll('_', ' ')}{['block', 'week', 'session', 'exercise_label', 'set_index'].includes(field) ? ' *' : ''}<input value={parsed.columns?.[field] || ''} maxLength={2} onChange={event => updateMapping(next => { next.columns ||= {}; if (event.target.value.trim()) next.columns[field] = event.target.value.toUpperCase(); else delete next.columns[field]; })} placeholder="Column letter" /></label>)}</div></div>}
                {parsed && <div className="alias-list"><h3>Exercise aliases</h3><p className="helper">Confirm canonical names for the source labels. New labels can be added after preview.</p>{draft?.exercise_labels?.some(label => !parsed.exercise_aliases?.[label]) && <button type="button" className="text-button" onClick={() => updateMapping(next => { next.exercise_aliases ||= {}; for (const label of draft.exercise_labels) next.exercise_aliases[label] ||= label; })}>Add detected source labels</button>}{Object.entries(parsed.exercise_aliases || {}).map(([source, canonical]) => <label key={source}><span>{source}</span><input value={String(canonical || '')} onChange={event => updateMapping(next => { next.exercise_aliases[source] = event.target.value; })} aria-label={`Canonical name for ${source}`} /></label>)}<div className="two-col"><label>New source label<input value={aliasSource} onChange={event => setAliasSource(event.target.value)} /></label><label>Canonical exercise<input value={aliasTarget} onChange={event => setAliasTarget(event.target.value)} /></label></div><button type="button" className="text-button" disabled={!aliasSource.trim() || !aliasTarget.trim()} onClick={() => { updateMapping(next => { next.exercise_aliases ||= {}; next.exercise_aliases[aliasSource.trim()] = aliasTarget.trim(); }); setAliasSource(''); setAliasTarget(''); }}>Add exercise alias</button></div>}
                {draft && <div className="mapping-summary"><h3>Mapped set preview</h3><p>{draft.row_count} candidate sets · {draft.blocking_count} blocking issues. No records have been committed.</p><div className="table-wrap"><table><thead><tr><th>Source</th><th>Block / week / day</th><th>Exercise</th><th>Set</th><th>Target reps</th><th>Actual reps</th></tr></thead><tbody>{draft.valid_sample_rows.map((row, index) => <tr key={`${row.source}-${index}`}><td>{row.source}</td><td>{row.block} / {row.week} / {row.session}</td><td>{row.exercise}</td><td>{row.set_index} {row.side}</td><td>{row.values.target_reps_min == null ? String(row.values.target_reps ?? '—') : `${row.values.target_reps_min}–${row.values.target_reps_max}`}</td><td>{String(row.values.reps ?? '—')}</td></tr>)}</tbody></table></div>{draft.issues_truncated && <p className="inline-error">More than 5,000 issues were found. Narrow the selected sheets to review them all.</p>}</div>}
                {draft && draft.issues.length > 0 && <div className="issue-list"><h3>Cells needing review</h3><p className="helper">Each selected ambiguous value needs its own decision. Re-preview after corrections.</p>{draft.issues.slice(issuePage * 20, issuePage * 20 + 20).map((issue, index) => { const cell = draft.correction_cells.find(item => item.location === issue.location); return <div className="issue blocking" key={`${issue.location}-${index}`}><b>!</b><div><p><strong>{issue.location}</strong> {issue.message}</p>{cell && <div className="correction-row">{cell.field === 'actual_status' ? <label>Actual status<select value={parsed?.actual_status_overrides?.[cell.location] || ''} onChange={event => updateMapping(next => { next.actual_status_overrides ||= {}; if (event.target.value) next.actual_status_overrides[cell.location] = event.target.value; else delete next.actual_status_overrides[cell.location]; })}><option value="">Choose status</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="unreported">Unreported</option></select></label> : <><label>{cell.field.replaceAll('_', ' ')} · source {cell.raw_value}<input type="number" min="0" step="any" value={parsed?.cell_overrides?.[cell.location] ?? ''} onChange={event => updateMapping(next => { next.cell_overrides ||= {}; if (event.target.value.trim()) next.cell_overrides[cell.location] = Number(event.target.value); else delete next.cell_overrides[cell.location]; })} /></label><button type="button" className="text-button" onClick={() => updateMapping(next => { next.cell_overrides ||= {}; next.cell_overrides[cell.location] = null; })}>Mark missing</button></>}</div>}</div></div>; })}<div className="issue-pages"><button type="button" disabled={issuePage === 0} onClick={() => setIssuePage(value => value - 1)}>Previous</button><span>Page {issuePage + 1} of {Math.ceil(draft.issues.length / 20)}</span><button type="button" disabled={(issuePage + 1) * 20 >= draft.issues.length} onClick={() => setIssuePage(value => value + 1)}>Next</button></div></div>}
                <details className="advanced-mapping"><summary>Advanced mapping JSON</summary><label htmlFor="mapping-json">Approved field mapping</label><textarea id="mapping-json" value={mapping} onChange={event => changeMapping(event.target.value)} spellCheck={false} rows={14} /><p className="helper">For row-per-set workbooks, set the sheet, header row, columns, and exercise aliases here.</p></details>
                {!parsed && <p className="inline-error">Mapping JSON must be a valid object.</p>}{missingBlock && <p className="inline-error">Enter a training block label.</p>}{missingAliases && <p className="inline-error">Confirm at least one exercise alias.</p>}{unresolved.length > 0 && <p className="inline-error">Resolve all ambiguous target cells before approval.</p>}
                <div className="approval-actions"><button type="button" disabled={!parsed || Boolean(busy)} onClick={previewMapping}>{busy === 'mapping-preview' ? 'Checking sets…' : 'Preview mapped sets'}</button><button type="button" disabled={!canApprove} onClick={approve}>{busy === 'approve' ? 'Approving…' : 'Approve mapping'}</button><button type="button" className="commit-button" disabled={!mappingId || Boolean(busy)} onClick={commit}>{busy === 'commit' ? 'Committing…' : 'Commit snapshot'}</button></div><p className="helper">Commit writes canonical training data. Approval alone does not.</p>
              </section>
            </>}
          </>}
        </>}
      </main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
