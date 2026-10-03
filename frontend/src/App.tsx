import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertCircle, ArrowDown, ArrowUpRight, Check, ChevronLeft, ChevronRight, Command, Filter, Flame, LogOut, MessageSquare, Plus, Search, ShieldCheck, UserRound, X } from 'lucide-react'

const API = `${window.location.protocol}//${window.location.hostname}:5000/api`
type User = { id: number; name: string; email: string; memberships?: { team_id: number; team: string; role: string }[] }
type Team = { id: number; name: string; role: string }
type Item = { id: number; title: string; description: string; team_id: number; team: string; status: string; priority: string; assignee_id: number | null; assignee: string | null; due_date: string | null; version: number; created_at: string; updated_at: string; activity?: { id: number; kind: string; message: string; actor: string; created_at: string }[] }
type Person = { id: number; name: string }
type TeamMember = { user_id: number; name: string; email: string; role: string }
type AvailableUser = { id: number; name: string; email: string }
type Page = { items: Item[]; page: number; pages: number; total: number }
type Dashboard = { my_open: number; unassigned: number; urgent: number; overdue: number; awaiting_my_approval: number }

class ApiError extends Error { status: number; data: any; constructor(status: number, data: any) { super(data.message || 'Something went wrong'); this.status = status; this.data = data } }
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: 'include', ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}
const qs = (values: Record<string, string | number | undefined>) => { const p = new URLSearchParams(); Object.entries(values).forEach(([k, v]) => { if (v !== undefined && v !== '' && v !== 'all') p.set(k, String(v)) }); return p.toString() }
const initials = (name: string) => name.split(' ').map((n) => n[0]).slice(0, 2).join('').toUpperCase()
const isOverdue = (item: Item) => item.due_date && item.due_date < new Date().toISOString().slice(0, 10) && item.status !== 'Resolved'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [teams, setTeams] = useState<Team[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [activeView, setActiveView] = useState<'all' | 'mine' | 'urgent'>('all')
  const [filters, setFilters] = useState({ q: '', team_id: 'all', status: 'all', priority: 'all' })
  const [selected, setSelected] = useState<Item | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [toast, setToast] = useState('')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [membershipTeam, setMembershipTeam] = useState<Team | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const teamNames = useMemo(() => teams.map((t) => t.name).join(' · '), [teams])
  const notify = useCallback((message: string) => setToast(message), [])

  useEffect(() => { api<{ user: User }>('/me').then((r) => setUser(r.user)).catch(() => setUser(null)) }, [])
  useEffect(() => {
    if (!user) return
    api<{ teams: Team[] }>('/teams').then((r) => setTeams(r.teams)).catch((e) => setError(e.message))
    api<{ counts: Dashboard }>('/dashboard').then((r) => setDashboard(r.counts)).catch(() => undefined)
  }, [user])
  const loadItems = useCallback(async () => {
    if (!user) return
    setLoading(true); setError('')
    try {
      const query = qs({ ...filters, page, per_page: 12, mine: activeView === 'mine' ? 'true' : undefined, priority: activeView === 'urgent' ? 'Urgent' : filters.priority })
      const result = await api<Page>(`/items?${query}`)
      setItems(result.items); setPages(Math.max(1, result.pages)); setTotal(result.total)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load the queue') }
    finally { setLoading(false) }
  }, [user, filters, page, activeView, refresh])
  useEffect(() => {
    const timer = window.setTimeout(loadItems, filters.q ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [loadItems, filters.q])
  useEffect(() => { setPage(1) }, [filters, activeView])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchRef.current?.focus()
      }
      if (event.key === 'Escape') {
        if (createOpen) setCreateOpen(false)
        else if (selected) setSelected(null)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [createOpen, selected])
  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  const signIn = async (email: string) => {
    setError('')
    try { const r = await api<{ user: User }>('/login', { method: 'POST', body: JSON.stringify({ email, password: 'demo1234' }) }); setUser(r.user) }
    catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed') }
  }
  const signOut = async () => { await api('/logout', { method: 'POST' }).catch(() => undefined); setUser(null); setTeams([]); setItems([]); setSelected(null) }
  const refreshItem = async (id: number) => { const r = await api<{ item: Item }>(`/items/${id}`); setSelected(r.item); setRefresh((n) => n + 1) }
  const createItem = async (data: object) => { const r = await api<{ item: Item }>('/items', { method: 'POST', body: JSON.stringify(data), headers: { 'Idempotency-Key': crypto.randomUUID() } }); setCreateOpen(false); setSelected(r.item); setPage(1); setRefresh((n) => n + 1); notify('Work item created.') }

  if (!user) return <Login onLogin={signIn} error={error} />
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Command size={17} strokeWidth={2.5} /></div><span>newtonite</span></div>
      <button className={`nav-link ${activeView === 'all' ? 'selected' : ''}`} onClick={() => setActiveView('all')}><Activity size={17} /> All work <span className="nav-count">{total}</span></button>
      <button className={`nav-link ${activeView === 'mine' ? 'selected' : ''}`} onClick={() => setActiveView('mine')}><UserRound size={17} /> Assigned to me</button>
      <button className={`nav-link ${activeView === 'urgent' ? 'selected' : ''}`} onClick={() => setActiveView('urgent')}><Flame size={17} /> Urgent</button>
      <div className="side-divider" />
      <div className="workspace-label team-heading">YOUR TEAMS <span>{teams.length}</span></div>
      {teams.map((team) => <button key={team.id} className={`team-link ${filters.team_id === String(team.id) ? 'team-active' : ''}`} onClick={() => setFilters({ ...filters, team_id: filters.team_id === String(team.id) ? 'all' : String(team.id) })}><span className="team-square">{team.name[0]}</span>{team.name}<span className="team-role">{team.role === 'lead' || team.role === 'manager' ? 'Team leader' : team.role === 'admin' ? 'Admin' : 'Member'}</span></button>)}
      {teams.some((team) => team.role === 'admin') && <button className="nav-link member-management-link" onClick={() => setMembershipTeam(teams.find((team) => team.role === 'admin') || null)}><ShieldCheck size={17} /> Manage members</button>}
      <div className="sidebar-bottom"><div className="avatar avatar-small">{initials(user.name)}</div><div className="signed-user"><strong>{user.name}</strong><span>{teamNames || 'Newtonite'}</span></div><button className="icon-button signout" title="Sign out" onClick={signOut}><LogOut size={16} /></button></div>
    </aside>

    <main className="main-area">
      <div className="content-wrap">
        <section className="page-heading"><div><h1>{activeView === 'mine' ? 'Your work' : activeView === 'urgent' ? 'Urgent work' : 'Work queue'}</h1></div><button className="primary-button" onClick={() => setCreateOpen(true)}><Plus size={17} /> New work item</button></section>
        {dashboard && <section className="metric-row" aria-label="Needs attention"><Metric label="Assigned to me" value={dashboard.my_open} icon={<UserRound size={15} />} /><Metric label="Urgent" value={dashboard.urgent} icon={<Flame size={15} />} /><Metric label="Overdue" value={dashboard.overdue} icon={<AlertCircle size={15} />} /><Metric label="Unassigned" value={dashboard.unassigned} icon={<Activity size={15} />} /></section>}
        <section className="queue-card">
          <div className="queue-header"><div><h2>Work items <span className="count-pill">{total}</span></h2></div><div className="sort-label"><ArrowDown size={14} /> Recently updated</div></div>
          <div className="toolbar"><label className="search-box"><Search size={16} /><input ref={searchRef} value={filters.q} placeholder="Search work items…" onChange={(e) => setFilters({ ...filters, q: e.target.value })} /><kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd></label><div className="filter-controls"><span className="filter-caption"><Filter size={14} /> FILTER</span><select aria-label="Filter by team" value={filters.team_id} onChange={(e) => setFilters({ ...filters, team_id: e.target.value })}><option value="all">All teams</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select><select aria-label="Filter by status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="all">Any status</option>{['Open', 'In progress', 'Waiting for approval', 'Blocked', 'Resolved'].map((s) => <option key={s}>{s}</option>)}</select><select aria-label="Filter by priority" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="all">Any priority</option>{['Urgent', 'High', 'Normal', 'Low'].map((p) => <option key={p}>{p}</option>)}</select></div></div>
          {error && <div className="inline-error"><AlertCircle size={15} /> {error}<button onClick={() => setRefresh((n) => n + 1)}>Retry</button></div>}
          <div className="table-head"><span>WORK ITEM</span><span>TEAM</span><span>PRIORITY</span><span>STATUS</span><span>OWNER</span><span>UPDATED</span><span /></div>
          <div className={`item-list ${loading ? 'is-loading' : ''}`}>
            {items.map((item) => <button className="item-row" key={item.id} onClick={() => refreshItem(item.id)}>
              <span className="item-title-cell"><span className={`priority-rail ${item.priority.toLowerCase()}`} /><span className="item-copy"><strong>{item.title}</strong><small>{isOverdue(item) ? <em className="overdue">Overdue · {item.due_date}</em> : item.due_date ? `Due ${item.due_date}` : item.description || 'No description added'}</small></span></span>
              <span className="team-cell"><span className="team-square tiny">{item.team[0]}</span>{item.team}</span><span><Priority value={item.priority} /></span><span><Status value={item.status} /></span><span className="owner-cell">{item.assignee ? <><span className="avatar avatar-row">{initials(item.assignee)}</span>{item.assignee.split(' ')[0]}</> : <span className="unassigned"><span /> Unassigned</span>}</span><span className="updated-cell">{timeAgo(item.updated_at)}</span><ArrowUpRight className="row-arrow" size={15} />
            </button>)}
            {!items.length && !loading && <div className="empty-state"><div className="empty-icon"><Check size={20} /></div><strong>Nothing needs your attention here.</strong><span>Try another filter or create a new work item.</span><button onClick={() => { setFilters({ q: '', team_id: 'all', status: 'all', priority: 'all' }); setActiveView('all') }}>Clear filters</button></div>}
          </div>
          <div className="pagination"><span>Showing <strong>{items.length ? (page - 1) * 12 + 1 : 0}–{Math.min(page * 12, total)}</strong> of <strong>{total}</strong> items</span><div className="page-actions"><button className="page-button" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={16} /> Previous</button><span className="page-number">{page} <i>/</i> {pages}</span><button className="page-button" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next <ChevronRight size={16} /></button></div></div>
        </section>
      </div>
    </main>
    {selected && <Detail item={selected} user={user} teams={teams} onClose={() => setSelected(null)} onRefresh={() => refreshItem(selected.id)} onNotify={notify} />}
    {createOpen && <CreateDialog teams={teams} onClose={() => setCreateOpen(false)} onCreate={createItem} />}
    {membershipTeam && <MembershipDialog team={membershipTeam} user={user} onClose={() => setMembershipTeam(null)} onNotify={notify} />}
    {toast && <div className="toast-message" role="status"><Check size={15} />{toast}</div>}
  </div>
}

function Login({ onLogin, error }: { onLogin: (email: string) => void; error: string }) {
  const [email, setEmail] = useState('alex@newtonite.local')
  return <div className="login-page"><div className="login-card"><div className="brand login-brand"><div className="brand-mark"><Command size={17} strokeWidth={2.5} /></div><span>newtonite</span></div><h1>Sign in</h1><label className="field-label">DEMO USER</label><select className="login-select" value={email} onChange={(e) => setEmail(e.target.value)}><option value="alex@newtonite.local">Alex Morgan · Member</option><option value="sam@newtonite.local">Sam Rivera · Team lead</option><option value="jordan@newtonite.local">Jordan Lee · Admin</option></select><button className="primary-button login-button" onClick={() => onLogin(email)}>Continue <ArrowUpRight size={17} /></button><div className="demo-note"><ShieldCheck size={15} /><span>Demo password: <code>demo1234</code></span></div>{error && <div className="inline-error"><AlertCircle size={15} /> {error}</div>}</div></div>
}

function Priority({ value }: { value: string }) { return <span className={`priority-chip ${value.toLowerCase()}`}>{value === 'Urgent' ? <Flame size={12} /> : value === 'High' ? <ArrowUpRight size={12} /> : value === 'Low' ? <ArrowDown size={12} /> : <span className="priority-dot" />}{value}</span> }
function Status({ value }: { value: string }) { const cls = value.toLowerCase().replace(/ /g, '-'); return <span className={`status-chip ${cls}`}><span className="status-dot" />{value}</span> }
function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) { return <div className="metric"><span className="metric-icon">{icon}</span><span><small className="metric-label">{label}</small><strong className="metric-value">{value}</strong></span></div> }
function timeAgo(value: string) { const diff = Math.max(0, Date.now() - new Date(value).getTime()); const mins = Math.floor(diff / 60000); if (mins < 1) return 'Just now'; if (mins < 60) return `${mins}m ago`; const hours = Math.floor(mins / 60); if (hours < 24) return `${hours}h ago`; const days = Math.floor(hours / 24); return days === 1 ? 'Yesterday' : `${days}d ago` }

function CreateDialog({ teams, onClose, onCreate }: { teams: Team[]; onClose: () => void; onCreate: (data: object) => Promise<void> }) {
  const [title, setTitle] = useState(''); const [description, setDescription] = useState(''); const [team, setTeam] = useState(teams[0]?.id.toString() || ''); const [priority, setPriority] = useState('Normal'); const [due, setDue] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  useEffect(() => {
    if (teams.length && !teams.some((entry) => String(entry.id) === team)) setTeam(String(teams[0].id))
  }, [teams, team])
  const submit = async (e: React.FormEvent) => { e.preventDefault(); setBusy(true); setError(''); try { await onCreate({ title, description, team_id: Number(team), priority, due_date: due || null }) } catch (e) { setError(e instanceof Error ? e.message : 'Could not create item') } finally { setBusy(false) } }
  return <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}><form className="create-modal" onSubmit={submit}><div className="modal-top"><div><span className="eyebrow">NEW REQUEST</span><h2>Put it on the board.</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div><label className="field-label">WHAT NEEDS TO HAPPEN?</label><input className="text-input title-input" autoFocus required maxLength={200} placeholder="A short, clear title" value={title} onChange={(e) => setTitle(e.target.value)} /><label className="field-label">GIVE YOUR TEAM SOME CONTEXT</label><textarea className="text-input" rows={4} placeholder="What happened? What have you tried?" value={description} onChange={(e) => setDescription(e.target.value)} /><div className="form-grid"><div><label className="field-label" htmlFor="create-team">TEAM</label><select id="create-team" aria-label="Team" className="text-input" required value={team} onChange={(e) => setTeam(e.target.value)}>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div><div><label className="field-label" htmlFor="create-priority">PRIORITY</label><select id="create-priority" aria-label="Priority" className="text-input" value={priority} onChange={(e) => setPriority(e.target.value)}>{['Low', 'Normal', 'High', 'Urgent'].map((p) => <option key={p}>{p}</option>)}</select></div></div><label className="field-label">DUE DATE <span className="optional">OPTIONAL</span></label><input className="text-input date-input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />{error && <div className="inline-error"><AlertCircle size={15} /> {error}</div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy || !teams.length}><Plus size={16} /> {busy ? 'Creating…' : 'Create work item'}</button></div></form></div>
}

function MembershipDialog({ team, user, onClose, onNotify }: { team: Team; user: User; onClose: () => void; onNotify: (message: string) => void }) {
  const [members, setMembers] = useState<TeamMember[]>([])
  const [available, setAvailable] = useState<AvailableUser[]>([])
  const [selectedUser, setSelectedUser] = useState('')
  const [newRole, setNewRole] = useState('member')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = async () => {
    try {
      const result = await api<{ members: TeamMember[]; available_users: AvailableUser[] }>(`/teams/${team.id}/members`)
      setMembers(result.members); setAvailable(result.available_users)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load team members') }
  }
  useEffect(() => { load() }, [team.id])
  const addMember = async (event: React.FormEvent) => {
    event.preventDefault(); if (!selectedUser) return
    setBusy(true); setError('')
    try { await api(`/teams/${team.id}/members`, { method: 'POST', body: JSON.stringify({ user_id: Number(selectedUser), role: newRole }) }); setSelectedUser(''); await load(); onNotify('Member added.') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not add member') }
    finally { setBusy(false) }
  }
  const changeRole = async (member: TeamMember, role: string) => {
    setBusy(true); setError('')
    try { await api(`/teams/${team.id}/members/${member.user_id}`, { method: 'PATCH', body: JSON.stringify({ role }) }); await load(); onNotify('Member role updated.') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not update role') }
    finally { setBusy(false) }
  }
  const removeMember = async (member: TeamMember) => {
    if (member.user_id === user.id || !window.confirm(`Remove ${member.name} from ${team.name}?`)) return
    setBusy(true); setError('')
    try { await api(`/teams/${team.id}/members/${member.user_id}`, { method: 'DELETE' }); await load(); onNotify('Member removed.') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not remove member') }
    finally { setBusy(false) }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="create-modal member-modal" aria-label="Manage team members"><div className="modal-top"><div><span className="eyebrow">TEAM ADMIN</span><h2>{team.name} members</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={19} /></button></div>{error && <div className="inline-error"><AlertCircle size={15} /> {error}</div>}<div className="member-list">{members.map((member) => <div className="member-row" key={member.user_id}><div><strong>{member.name}</strong><small>{member.email}</small></div><select aria-label={`Role for ${member.name}`} value={member.role} disabled={busy} onChange={(event) => changeRole(member, event.target.value)}><option value="member">Member</option><option value="lead">Team leader</option><option value="admin">Admin</option></select><button className="secondary-button" disabled={busy || member.user_id === user.id} onClick={() => removeMember(member)}>Remove</button></div>)}</div><form className="member-add" onSubmit={addMember}><label className="field-label" htmlFor="member-user">ADD MEMBER</label><div className="member-add-row"><select id="member-user" className="text-input" value={selectedUser} onChange={(event) => setSelectedUser(event.target.value)} required><option value="">Choose a user</option>{available.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name} · {candidate.email}</option>)}</select><select className="text-input" aria-label="New member role" value={newRole} onChange={(event) => setNewRole(event.target.value)}><option value="member">Member</option><option value="lead">Team leader</option><option value="admin">Admin</option></select><button className="primary-button" disabled={busy || !selectedUser}><Plus size={15} /> Add</button></div></form><div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Done</button></div></section></div>
}

function Detail({ item, user, teams, onClose, onRefresh, onNotify }: { item: Item; user: User; teams: Team[]; onClose: () => void; onRefresh: () => void; onNotify: (message: string) => void }) {
  const role = user.memberships?.find((m) => m.team_id === item.team_id)?.role || 'member'; const canLead = role === 'manager' || role === 'lead'; const canEdit = canLead
  const [people, setPeople] = useState<Person[]>([]); const [comment, setComment] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [editing, setEditing] = useState(false); const [titleDraft, setTitleDraft] = useState(item.title); const [descriptionDraft, setDescriptionDraft] = useState(item.description)
  useEffect(() => { api<{ users: Person[] }>(`/users?team_id=${item.team_id}`).then((r) => setPeople(r.users)).catch(() => undefined) }, [item.team_id])
  const action = async (path: string, body: object): Promise<boolean> => { setBusy(true); setError(''); try { await api(`/items/${item.id}${path}`, { method: path === '' ? 'PATCH' : 'POST', body: JSON.stringify(body), headers: { 'Idempotency-Key': crypto.randomUUID() } }); onRefresh(); const values = body as Record<string, unknown>; onNotify(path === '/claim' ? 'You claimed this item.' : path === '/comments' ? 'Comment added.' : values.status ? 'Status updated.' : values.assignee_id !== undefined ? 'Owner updated.' : values.priority ? 'Priority updated.' : 'Changes saved.'); return true } catch (e) { const message = e instanceof ApiError && e.status === 409 ? 'This item was changed by someone else. The latest version is shown below.' : e instanceof Error ? e.message : 'Action failed'; setError(message); if (e instanceof ApiError && e.data.item) onRefresh(); return false } finally { setBusy(false) } }
  const change = (field: string, value: string | number | null) => action('', { version: item.version, [field]: value })
  const saveDescription = async () => { if (await action('', { version: item.version, title: titleDraft, description: descriptionDraft })) setEditing(false) }
  const addComment = async (e: React.FormEvent) => { e.preventDefault(); if (!comment.trim()) return; if (await action('/comments', { message: comment })) setComment('') }
  const nextStatuses = item.status === 'Open' ? ['In progress', 'Blocked'] : item.status === 'In progress' ? ['Waiting for approval', 'Blocked', 'Resolved', 'Open'] : item.status === 'Waiting for approval' ? ['In progress', 'Blocked', 'Resolved'] : item.status === 'Blocked' ? ['Open', 'In progress'] : []
  return <div className="detail-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}><aside className="detail-panel"><div className="detail-top"><span className="detail-label"><span className="detail-bullet" /> WORK ITEM <span className="detail-id">#{String(item.id).padStart(4, '0')}</span></span><div className="detail-top-actions">{canEdit && <button className="edit-text-button" onClick={() => setEditing(!editing)}>{editing ? 'Cancel edit' : 'Edit details'}</button>}<button className="icon-button" onClick={onClose}><X size={19} /></button></div></div><div className="detail-scroll"><div className="detail-team">{item.team} <span>·</span> Created {new Date(item.created_at).toLocaleDateString()}</div>{editing ? <div className="edit-details"><label className="field-label">TITLE</label><input className="text-input" value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} maxLength={200} /><label className="field-label">DESCRIPTION</label><textarea className="text-input" rows={4} value={descriptionDraft} onChange={(e) => setDescriptionDraft(e.target.value)} /><button className="primary-button save-details" disabled={busy || !titleDraft.trim()} onClick={saveDescription}><Check size={14} /> Save details</button></div> : <><h2>{item.title}</h2><p className="detail-description">{item.description || 'No description yet.'}</p></>}<div className="detail-badges"><Status value={item.status} /><Priority value={item.priority} /></div>
    <div className="detail-fields"><div className="detail-field"><span>OWNER</span>{canLead ? <select value={item.assignee_id ?? ''} onChange={(e) => change('assignee_id', e.target.value ? Number(e.target.value) : null)}><option value="">Unassigned</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select> : <div className="owner-detail">{item.assignee ? <><span className="avatar avatar-row">{initials(item.assignee)}</span>{item.assignee}</> : <span className="unassigned"><span /> Unassigned</span>}</div>}</div><div className="detail-field"><span>PRIORITY</span>{canEdit ? <select value={item.priority} onChange={(e) => change('priority', e.target.value)}>{['Low', 'Normal', 'High', 'Urgent'].map((p) => <option key={p}>{p}</option>)}</select> : <Priority value={item.priority} />}</div><div className="detail-field"><span>DUE DATE</span>{canLead ? <input type="date" value={item.due_date || ''} onChange={(e) => change('due_date', e.target.value || null)} /> : <strong>{item.due_date || 'No due date'}</strong>}</div><div className="detail-field"><span>LAST UPDATED</span><strong>{timeAgo(item.updated_at)}</strong></div></div>
    {canLead && nextStatuses.length > 0 && <div className="workflow-box"><div><span className="field-label">MOVE THIS WORK FORWARD</span><span className="workflow-hint">Current: {item.status}</span></div><select value="" onChange={(e) => e.target.value && change('status', e.target.value)}><option value="">Choose next step…</option>{nextStatuses.map((s) => <option key={s}>{s}</option>)}</select></div>}
    {item.assignee_id === null && <button className="claim-button" disabled={busy} onClick={() => action('/claim', { version: item.version })}><UserRound size={16} /> Claim this item</button>}
    {error && <div className="inline-error"><AlertCircle size={15} /> {error} <button onClick={onRefresh}>Reload</button></div>}
    <div className="activity-heading"><div><Activity size={16} /><strong>Activity</strong><span>{item.activity?.length || 0}</span></div></div><div className="activity-feed">{item.activity?.map((entry) => <div className="activity-entry" key={entry.id}><div className={`activity-icon ${entry.kind}`}><Activity size={13} /></div><div><p><strong>{entry.actor}</strong> {entry.kind === 'comment' ? 'left a note' : entry.message}</p>{entry.kind === 'comment' && <blockquote>{entry.message}</blockquote>}<time>{new Date(entry.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></div></div>)}</div>
    </div><form className="comment-box" onSubmit={addComment}><div className="comment-composer"><span className="avatar avatar-row">{initials(user.name)}</span><textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Leave a note for the team…" rows={2} /><button type="submit" disabled={busy || !comment.trim()} aria-label="Send comment"><ArrowUpRight size={17} /></button></div><div className="comment-hint"><MessageSquare size={12} /> Your comment is visible to everyone on the team.</div></form></aside></div>
}
