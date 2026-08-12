// ==================== Live Counter Engine ====================

let currentDetailTest = null;   // test object shown in detail view
let liveTestData = [];          // all tests being tracked
let counterTick = null;         // setInterval handle
const SYNC_INTERVAL_MIN = 240;  // default 4 hours

/** Global system pause state – populated by fetchSystemState() */
let systemState = {
    is_paused: false,
    paused_at: null,
    paused_by_name: null,
    total_paused_minutes_ever: 0
};

/** Testing Summary table state — data cache, search, sort and pagination */
let summaryState = {
    rows: [],          // normalized row objects for all tests (ongoing + completed)
    search: '',
    sortKey: null,     // 'status' | 'start' | 'end' | 'duration' — null = default grouped order
    sortDir: 'asc',
    page: 1,
    pageSize: 10
};

/** Normalise an ISO datetime string to always be parsed as UTC */
function toUtcMs(iso) {
    if (!iso) return 0;
    // Append Z if no timezone info present, so JS treats it as UTC
    const s = /[Zz]$|[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z';
    return new Date(s).getTime();
}

/**
 * Effective "now" in ms — frozen at paused_at when system is paused.
 * @param {boolean} isPaused
 * @param {string|null} pausedAt  ISO string
 */
function effectiveNowMs(isPaused, pausedAt) {
    return (isPaused && pausedAt) ? toUtcMs(pausedAt) : Date.now();
}

/**
 * Resolve the pause context for a single test/slot.
 * A slot's timeline freezes if the slot itself is paused OR the whole system is
 * paused — whichever started first. This keeps each slot independent while still
 * honouring a global factory off-day pause.
 * @returns {{isPaused: boolean, pausedAt: string|null}}
 */
function testPauseContext(test) {
    let pausedMs = null;
    if (test.status === 'paused' && test.paused_at) {
        pausedMs = toUtcMs(test.paused_at);
    }
    if (systemState.is_paused && systemState.paused_at) {
        const sysMs = toUtcMs(systemState.paused_at);
        pausedMs = (pausedMs === null) ? sysMs : Math.min(pausedMs, sysMs);
    }
    if (pausedMs === null) return { isPaused: false, pausedAt: null };
    return { isPaused: true, pausedAt: new Date(pausedMs).toISOString() };
}

/** Calculate ON time accumulated since last sync (seconds), subtracting paused time */
function calcOnSeconds(syncedAt, onMinutes, offMinutes, pausedSecSinceSync, isPaused, pausedAt) {
    const nowMs  = effectiveNowMs(isPaused, pausedAt);
    const syncMs = toUtcMs(syncedAt);
    const rawElapsed = Math.max(0, (nowMs - syncMs) / 1000);
    const elapsed    = Math.max(0, rawElapsed - (pausedSecSinceSync || 0));
    const onSec   = onMinutes * 60;
    const cycleSec = (onMinutes + offMinutes) * 60;
    const full     = Math.floor(elapsed / cycleSec);
    const rem      = elapsed % cycleSec;
    return full * onSec + Math.min(rem, onSec);
}

/** Estimate current machine hours */
function estimateHours(lastSyncHours, syncedAt, onMinutes, offMinutes, pausedSecSinceSync, isPaused, pausedAt) {
    return lastSyncHours + calcOnSeconds(syncedAt, onMinutes, offMinutes, pausedSecSinceSync, isPaused, pausedAt) / 3600;
}

/** Return {state, remainSec} for the current cycle phase */
function cycleState(syncedAt, onMinutes, offMinutes, pausedSecSinceSync, isPaused, pausedAt) {
    const nowMs    = effectiveNowMs(isPaused, pausedAt);
    const syncMs   = toUtcMs(syncedAt);
    const rawElapsed = Math.max(0, (nowMs - syncMs) / 1000);
    const elapsed    = Math.max(0, rawElapsed - (pausedSecSinceSync || 0));
    const onSec    = onMinutes * 60;
    const cycleSec = (onMinutes + offMinutes) * 60;
    const pos = ((elapsed % cycleSec) + cycleSec) % cycleSec;
    if (pos < onSec) return { state: 'ON',  remainSec: Math.ceil(onSec - pos) };
    return            { state: 'OFF', remainSec: Math.ceil(cycleSec - pos) };
}

/** Seconds until next sync is due (using effective elapsed time, so pause suspends countdown) */
function secondsUntilNextSync(syncedAt, intervalMin, pausedSecSinceSync, isPaused, pausedAt) {
    const nowMs   = effectiveNowMs(isPaused, pausedAt);
    const syncMs  = toUtcMs(syncedAt);
    const rawElapsed = Math.max(0, (nowMs - syncMs) / 1000);
    const effectiveElapsed = Math.max(0, rawElapsed - (pausedSecSinceSync || 0));
    return Math.max(0, Math.round(intervalMin * 60 - effectiveElapsed));
}

function fmtHMS(hours) {
    const totalSec = Math.floor(hours * 3600);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;
}

function fmtHM(hours) {
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return `${h}h ${String(m).padStart(2,'0')}m`;
}

function fmtSec(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2,'0')}m`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

/** Format a duration in seconds as "Xd Yh Zm" (or "Hh Mm" / "Mm") */
function fmtDuration(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function fmtDateTime(iso) {
    if (!iso) return '--';
    return new Date(iso).toLocaleString();
}

function fmtTime(iso) {
    if (!iso) return '--:--';
    return new Date(iso).toLocaleTimeString();
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

/** Map an internal status value to its user-facing label (value stays unchanged) */
function statusLabel(status) {
    return { running: 'Ongoing', completed: 'Completed', paused: 'Paused' }[status] || status || '';
}

/** Escape a value for safe interpolation into innerHTML (prevents stored XSS) */
function esc(val) {
    if (val == null) return '';
    return String(val).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

// ── Tick every second ──
function startCounterTick() {
    if (counterTick) clearInterval(counterTick);
    counterTick = setInterval(tick, 1000);
    tick(); // immediate first render
}

function tick() {
    // Update dashboard cards (running and paused slots; each slot is independent)
    liveTestData.forEach(test => {
        if (!test.last_sync) return;
        if (test.status !== 'running' && test.status !== 'paused') return;
        const { isPaused, pausedAt } = testPauseContext(test);
        const ls  = test.last_sync;
        const syncedAt = ls.syncedAt || ls.synced_at;
        const psec = test.paused_seconds_since_sync || 0;
        const est = estimateHours(ls.machine_hours, syncedAt, test.on_minutes, test.off_minutes, psec, isPaused, pausedAt);
        const cs  = cycleState(syncedAt, test.on_minutes, test.off_minutes, psec, isPaused, pausedAt);
        const nxt = secondsUntilNextSync(syncedAt, SYNC_INTERVAL_MIN, psec, isPaused, pausedAt);

        const cardEst = document.getElementById(`card-est-${test.id}`);
        if (cardEst) cardEst.textContent = fmtHMS(est);
        const stateEl = document.getElementById(`card-state-${test.id}`);
        if (stateEl) {
            stateEl.textContent = isPaused ? 'PAUSED' : (cs.state === 'ON' ? 'ON' : 'OFF');
            stateEl.className   = isPaused ? 'cycle-badge paused' : `cycle-badge ${cs.state === 'ON' ? 'on' : 'off'}`;
        }
        setText(`card-remain-${test.id}`, isPaused ? '--:--' : fmtSec(cs.remainSec));
        setText(`card-next-${test.id}`,   isPaused ? 'Paused' : (nxt > 0 ? fmtSec(nxt) : 'OVERDUE'));

        const nxtEl = document.getElementById(`card-next-${test.id}`);
        if (nxtEl) nxtEl.className = (!isPaused && nxt === 0) ? 'overdue' : '';
    });

    // Update detail view — running or paused (paused shows a frozen counter)
    if (currentDetailTest && (currentDetailTest.status === 'running' || currentDetailTest.status === 'paused') && currentDetailTest.last_sync) {
        const t  = currentDetailTest;
        const { isPaused, pausedAt } = testPauseContext(t);
        const ls = t.last_sync;
        const syncedAt = ls.syncedAt || ls.synced_at;
        const psec = t.paused_seconds_since_sync || 0;
        const est = estimateHours(ls.machine_hours, syncedAt, t.on_minutes, t.off_minutes, psec, isPaused, pausedAt);
        const cs  = cycleState(syncedAt, t.on_minutes, t.off_minutes, psec, isPaused, pausedAt);
        const nxt = secondsUntilNextSync(syncedAt, SYNC_INTERVAL_MIN, psec, isPaused, pausedAt);
        const pct = Math.min(est / t.target_hours * 100, 100);

        setText('detailCounter', fmtHMS(est));
        setText('detailProgress', pct.toFixed(1) + '%');
        const fill = document.getElementById('detailProgressFill');
        if (fill) fill.style.width = pct.toFixed(1) + '%';

        const stEl = document.getElementById('detailCycleState');
        if (stEl) {
            stEl.textContent = isPaused ? 'PAUSED' : (cs.state === 'ON' ? 'ON' : 'OFF');
            stEl.className   = isPaused ? 'cycle-state-big paused' : `cycle-state-big ${cs.state === 'ON' ? 'on' : 'off'}`;
        }
        setText('detailCycleRemain', isPaused ? '--:--' : fmtSec(cs.remainSec));

        const nxtEl = document.getElementById('detailNextSync');
        if (nxtEl) {
            nxtEl.textContent = isPaused ? 'Paused' : (nxt > 0 ? fmtSec(nxt) : 'OVERDUE');
            nxtEl.className   = `sync-info-val sync-countdown${(!isPaused && nxt === 0) ? ' overdue' : ''}`;
        }
    }
}

// ==================== Auth ====================

function showToast(msg, type = 'info') {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.className = `toast ${type}`;
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 3500);
}

/**
 * Themed confirmation dialog (replaces the native confirm()).
 * Returns a Promise<boolean> — true on OK, false on Cancel/Esc/backdrop.
 */
function confirmDialog({ title = 'Are you sure?', message = '', okText = 'OK',
                         cancelText = 'Cancel', okClass = 'btn-primary', icon = '' } = {}) {
    return new Promise(resolve => {
        const overlay = document.getElementById('confirmOverlay');
        if (!overlay) { resolve(window.confirm(message)); return; }

        document.getElementById('confirmTitle').textContent = title;
        document.getElementById('confirmMessage').textContent = message;
        const iconEl = document.getElementById('confirmIcon');
        iconEl.innerHTML = icon || '';
        iconEl.style.display = icon ? '' : 'none';

        const okBtn = document.getElementById('confirmOk');
        const cancelBtn = document.getElementById('confirmCancel');
        okBtn.textContent = okText;
        cancelBtn.textContent = cancelText;
        okBtn.className = `btn ${okClass}`;
        overlay.style.display = 'flex';

        function cleanup(result) {
            overlay.style.display = 'none';
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            overlay.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onKey);
            resolve(result);
        }
        const onOk = () => cleanup(true);
        const onCancel = () => cleanup(false);
        const onBackdrop = (e) => { if (e.target === overlay) cleanup(false); };
        const onKey = (e) => {
            if (e.key === 'Escape') cleanup(false);
            else if (e.key === 'Enter') cleanup(true);
        };
        okBtn.addEventListener('click', onOk);
        cancelBtn.addEventListener('click', onCancel);
        overlay.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onKey);
        okBtn.focus();
    });
}

function switchLoginTab(name, btn) {
    document.querySelectorAll('.tab-content').forEach(e => e.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(e => e.classList.remove('active'));
    document.getElementById(name + 'Tab').classList.add('active');
    btn.classList.add('active');
}

async function handleLogin(e) {
    e.preventDefault();
    try {
        const res = await api.login(
            document.getElementById('loginEmail').value,
            document.getElementById('loginPassword').value
        );
        api.setToken(res.access_token);
        api.setUser(res.user);
        showDashboard();
    } catch(err) { showToast(err.message, 'error'); }
}

async function handleRegister(e) {
    e.preventDefault();
    try {
        const res = await api.register(
            document.getElementById('registerEmail').value,
            document.getElementById('registerPassword').value,
            document.getElementById('registerName').value
        );
        api.setToken(res.access_token);
        api.setUser(res.user);
        showDashboard();
    } catch(err) { showToast(err.message, 'error'); }
}

function handleLogout() {
    if (counterTick) clearInterval(counterTick);
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
    location.reload();
}

// ==================== Navigation ====================

function showSection(name, navEl) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const sec = document.getElementById(name + 'Section');
    if (sec) sec.classList.add('active');
    if (navEl) navEl.classList.add('active');

    if (name === 'dashboard') loadLifeTests();
    if (name === 'summary')   loadSummaryTable();
    if (name === 'reports')   loadReports();
    if (name === 'settings')  loadSettings();
}

function showDashboard() {
    document.getElementById('loginView').style.display = 'none';
    document.getElementById('dashboardView').style.display = 'flex';

    const user = api.user;
    setText('navUserName', user.full_name || user.email);
    const roleLabel = { operator: 'Operator', access_person: 'Supervisor', admin: 'Admin' };
    const roleBadge = document.getElementById('navUserRole');
    if (roleBadge) {
        roleBadge.textContent = roleLabel[user.role] || user.role;
        roleBadge.className = `role-badge role-${user.role}`;
    }

    const isOp    = user.role === 'operator';
    const isAP    = user.role === 'access_person';
    const isAdmin = user.role === 'admin';

    const show = (id, v) => { const el = document.getElementById(id); if(el) el.style.display = v ? '' : 'none'; };
    show('navNewTest',   isOp || isAdmin);
    show('navReports',   isAP || isAdmin);
    show('navSettings',  isAdmin);
    show('dashNewTestBtn', isOp || isAdmin);
    // Pause button visible for operators and admins only
    show('pauseAllBtn', isOp || isAdmin);

    loadLifeTests();
    fetchSystemState();   // load pause state before starting tick
    startCounterTick();
}

// ==================== Life Tests ====================

/** Fetch and cache system pause state, then update UI */
async function fetchSystemState() {
    try {
        const res = await api.getSystemState();
        systemState.is_paused              = res.is_paused;
        systemState.paused_at             = res.paused_at || null;
        systemState.paused_by_name        = res.paused_by_name || null;
        systemState.total_paused_minutes_ever = res.total_paused_minutes_ever || 0;
        updatePauseBanner();
        updatePauseButton();
    } catch (err) {
        console.warn('Could not fetch system state:', err.message);
    }
}

/** Show/hide and populate the system pause banner */
function updatePauseBanner() {
    const banner = document.getElementById('systemPauseBanner');
    const detail = document.getElementById('pauseBannerDetail');
    if (!banner) return;
    if (systemState.is_paused) {
        const who  = systemState.paused_by_name ? ` — paused by ${systemState.paused_by_name}` : '';
        const when = systemState.paused_at ? ` at ${new Date(systemState.paused_at).toLocaleString()}` : '';
        if (detail) detail.textContent = `All timers are frozen${who}${when}. Resume when factory operations restart.`;
        banner.style.display = 'flex';
    } else {
        banner.style.display = 'none';
    }
}

/** Update pause/resume button label and style */
function updatePauseButton() {
    const btn = document.getElementById('pauseAllBtn');
    if (!btn) return;
    if (systemState.is_paused) {
        btn.innerHTML = '&#9654; Resume All Slots';
        btn.className = 'btn btn-sm btn-resume';
    } else {
        btn.innerHTML = '&#9208; Pause All Slots';
        btn.className = 'btn btn-sm btn-warning';
    }
}

/** Handle click on the Pause / Resume All Slots button */
async function handlePauseResumeAll() {
    const action = systemState.is_paused ? 'resume' : 'pause';
    const label  = systemState.is_paused ? 'Resume' : 'Pause';
    const ok = await confirmDialog({
        title: `${label} ALL slots?`,
        message: action === 'pause'
            ? 'This will freeze all running time counters. Use this on non-working days (e.g. Sundays).'
            : 'This will restart all time counters from where they left off.',
        okText: action === 'pause' ? 'Pause All' : 'Resume All',
        okClass: action === 'pause' ? 'btn-warning' : 'btn-resume',
        icon: action === 'pause' ? '&#9208;' : '&#9654;'
    });
    if (!ok) return;
    try {
        if (action === 'pause') {
            await api.pauseSystem('Factory off-day pause');
            showToast('System paused — all timers frozen.', 'warning');
        } else {
            const res = await api.resumeSystem('Factory operations resumed');
            const shifted = res && res.ecd_updated_count > 0
                ? ` ECD shifted +${res.ecd_shifted_days}d on ${res.ecd_updated_count} test(s).`
                : '';
            showToast('System resumed — timers restarted.' + shifted, 'success');
        }
        // Re-fetch system state and life tests to get updated paused_seconds_since_sync
        await fetchSystemState();
        await loadLifeTests();
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function loadLifeTests() {
    const status = document.getElementById('filterStatus')?.value || '';
    const grid = document.getElementById('testsGrid');
    if (!grid) return;
    try {
        const res = await api.getLifeTests(status);
        liveTestData = res.life_tests || [];
        // Sync global system state from the list response (enriched by backend)
        if (liveTestData.length > 0) {
            const first = liveTestData[0];
            if (first.system_is_paused !== undefined) {
                systemState.is_paused = first.system_is_paused;
                systemState.paused_at = first.system_paused_at || null;
                updatePauseBanner();
                updatePauseButton();
            }
        }
        if (liveTestData.length === 0) {
            const isOp = api.user && (api.user.role === 'operator' || api.user.role === 'admin');
            grid.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon">&#128202;</div>
                <div>No life tests found.</div>
                ${isOp ? '<div style="margin-top:12px"><button class="btn btn-primary" onclick="showSection(\'newTest\', document.getElementById(\'navNewTest\'))">+ Start a New Life Test</button></div>' : ''}
            </div>`;
            return;
        }
        grid.innerHTML = liveTestData.map(renderTestCard).join('');
    } catch(err) {
        grid.innerHTML = `<div class="empty-state error">${err.message}</div>`;
    }
}

// ==================== Testing Summary Table ====================

const MS_PER_DAY = 86400000;

/** Reduce an ISO datetime (UTC) or a plain YYYY-MM-DD date to local-midnight ms. */
function dayStartMs(value) {
    if (!value) return null;
    let d;
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        // Plain date (e.g. ECD) — construct at local midnight, no TZ shift
        const [y, m, day] = value.split('-').map(Number);
        d = new Date(y, m - 1, day);
    } else {
        // Full datetime stored as UTC — normalize then drop the time component
        const ms = toUtcMs(value);
        if (!ms) return null;
        const t = new Date(ms);
        d = new Date(t.getFullYear(), t.getMonth(), t.getDate());
    }
    return d.getTime();
}

/** Whole-day difference between two day-start timestamps (end - start), or null. */
function diffDays(startMs, endMs) {
    if (startMs == null || endMs == null) return null;
    return Math.max(0, Math.round((endMs - startMs) / MS_PER_DAY));
}

/** Format a YYYY-MM-DD from a day-start ms value. */
function fmtDateShort(ms) {
    if (ms == null) return null;
    const d = new Date(ms);
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function daysLabel(n) {
    return n == null ? '—' : `${n} day${n === 1 ? '' : 's'}`;
}

/** Fetch every life test and build normalized rows for the summary table. */
async function loadSummaryTable() {
    const body = document.getElementById('summaryTableBody');
    if (!body) return;
    try {
        const res = await api.getLifeTests('');   // no filter → all statuses
        const tests = res.life_tests || [];
        summaryState.rows = tests.map(t => {
            const startMs = dayStartMs(t.created_at);
            const isCompleted = t.status === 'completed';
            // End: completed → actual completion date; otherwise → ECD (expected)
            const endMs = isCompleted ? dayStartMs(t.completed_at) : dayStartMs(t.ecd);
            const totalDays = diffDays(startMs, endMs);
            const elapsedDays = diffDays(startMs, dayStartMs(new Date().toISOString()));
            return {
                id: t.id,
                status: t.status,
                product: t.product || '',
                datecode: t.datecode || '',
                startMs,
                endMs,
                endIsExpected: !isCompleted,
                totalDays,
                elapsedDays,
                isCompleted
            };
        });
        summaryState.page = 1;
        renderSummaryTable();
    } catch (err) {
        body.innerHTML = `<tr><td colspan="6" class="empty-state error">${esc(err.message)}</td></tr>`;
    }
}

/** Apply search + sort, then render the current page of the summary table. */
function renderSummaryTable() {
    const body = document.getElementById('summaryTableBody');
    if (!body) return;

    // 1) Filter by search (product or model)
    const q = summaryState.search.trim().toLowerCase();
    let rows = summaryState.rows.filter(r =>
        !q || r.product.toLowerCase().includes(q) || r.datecode.toLowerCase().includes(q));

    // 2) Sort
    const key = summaryState.sortKey;
    if (key) {
        const dir = summaryState.sortDir === 'asc' ? 1 : -1;
        const val = (r) => {
            switch (key) {
                case 'status':   return r.status;
                case 'start':    return r.startMs ?? 0;
                case 'end':      return r.endMs ?? 0;
                case 'duration': return r.totalDays ?? -1;
            }
        };
        rows = rows.slice().sort((a, b) => {
            const va = val(a), vb = val(b);
            if (va < vb) return -1 * dir;
            if (va > vb) return 1 * dir;
            return 0;
        });
    } else {
        // Default grouped order: Ongoing (oldest start first), then Completed
        // (most recent completion first). 'paused' counts as ongoing/live.
        const ongoing = rows.filter(r => !r.isCompleted)
            .sort((a, b) => (a.startMs ?? 0) - (b.startMs ?? 0));
        const completed = rows.filter(r => r.isCompleted)
            .sort((a, b) => (b.endMs ?? 0) - (a.endMs ?? 0));
        rows = ongoing.concat(completed);
    }

    // 3) Update sort caret indicators on headers
    document.querySelectorAll('.summary-table th.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.key === key) th.classList.add(summaryState.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
    });

    const total = rows.length;
    if (total === 0) {
        body.innerHTML = `<tr><td colspan="6" class="empty-state">${q ? 'No machines match your search.' : 'No testing records yet.'}</td></tr>`;
        document.getElementById('summaryCount').textContent = '';
        document.getElementById('summaryPagination').innerHTML = '';
        return;
    }

    // 4) Paginate
    const pageSize = summaryState.pageSize;
    const pageCount = Math.ceil(total / pageSize);
    if (summaryState.page > pageCount) summaryState.page = pageCount;
    const start = (summaryState.page - 1) * pageSize;
    const pageRows = rows.slice(start, start + pageSize);

    body.innerHTML = pageRows.map(renderSummaryRow).join('');

    // 5) Footer: count + pagination controls
    const from = start + 1, to = start + pageRows.length;
    document.getElementById('summaryCount').textContent = `Showing ${from}–${to} of ${total} machine${total === 1 ? '' : 's'}`;
    renderSummaryPagination(pageCount);
}

function renderSummaryRow(r) {
    const startStr = fmtDateShort(r.startMs) || '<span class="date-muted">—</span>';
    let endStr;
    if (r.endMs != null) {
        endStr = fmtDateShort(r.endMs) + (r.endIsExpected ? ' <span class="date-muted">(expected)</span>' : '');
    } else {
        endStr = '<span class="date-muted">' + (r.endIsExpected ? 'ECD not set' : '—') + '</span>';
    }

    // Duration cell: ongoing → planned + elapsed; completed → actual total
    let durHtml;
    if (r.isCompleted) {
        durHtml = `<span class="dur-primary">${daysLabel(r.totalDays)}</span>`;
    } else {
        const planned = r.totalDays != null
            ? `<span class="dur-primary">${daysLabel(r.totalDays)} planned</span>`
            : `<span class="dur-primary">—</span>`;
        durHtml = `${planned}<span class="dur-sub">${daysLabel(r.elapsedDays)} elapsed</span>`;
    }

    return `
    <tr onclick="openTestDetail('${esc(r.id)}')" style="cursor:pointer;">
        <td class="col-status"><span class="status-badge status-${esc(r.status)}">${esc(statusLabel(r.status))}</span></td>
        <td class="col-product">${esc(r.product) || '<span class="date-muted">—</span>'}</td>
        <td class="col-datecode"><span class="datecode-id">${r.datecode ? esc(r.datecode) : '<span class="date-muted">—</span>'}</span></td>
        <td class="col-date">${startStr}</td>
        <td class="col-date">${endStr}</td>
        <td class="col-duration">${durHtml}</td>
    </tr>`;
}

function renderSummaryPagination(pageCount) {
    const wrap = document.getElementById('summaryPagination');
    if (!wrap) return;
    if (pageCount <= 1) { wrap.innerHTML = ''; return; }
    const cur = summaryState.page;
    let html = `<button ${cur === 1 ? 'disabled' : ''} onclick="summaryGoPage(${cur - 1})">‹</button>`;
    for (let p = 1; p <= pageCount; p++) {
        html += `<button class="${p === cur ? 'active' : ''}" onclick="summaryGoPage(${p})">${p}</button>`;
    }
    html += `<button ${cur === pageCount ? 'disabled' : ''} onclick="summaryGoPage(${cur + 1})">›</button>`;
    wrap.innerHTML = html;
}

function summaryGoPage(p) {
    summaryState.page = p;
    renderSummaryTable();
}

function onSummarySearch() {
    summaryState.search = document.getElementById('summarySearch').value || '';
    summaryState.page = 1;
    renderSummaryTable();
}

/** Toggle sort on a column; clicking the active column flips direction. */
function summarySort(key) {
    if (summaryState.sortKey === key) {
        summaryState.sortDir = summaryState.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        summaryState.sortKey = key;
        // Sensible defaults: dates/duration newest-or-largest first feels natural,
        // status ascending groups the statuses.
        summaryState.sortDir = (key === 'status') ? 'asc' : 'desc';
    }
    summaryState.page = 1;
    renderSummaryTable();
}

function renderTestCard(test) {
    const ls = test.last_sync;
    const syncedAt = ls ? (ls.syncedAt || ls.synced_at) : null;
    const hasSync = !!ls;
    const isRunning = test.status === 'running';
    const isPausedStatus = test.status === 'paused';
    const isLive = isRunning || isPausedStatus;   // slot with a live/frozen counter

    const isOp = api.user && (api.user.role === 'operator' || api.user.role === 'admin');
    const canPause = isOp && isLive;
    const pauseBtnHtml = canPause ? `
        <div class="test-card-actions">
            <button class="btn btn-sm ${isPausedStatus ? 'btn-resume' : 'btn-warning'} card-pause-btn"
                onclick="handleCardPauseToggle('${esc(test.id)}', event)">
                ${isPausedStatus ? '&#9654; Resume Slot' : '&#9208; Pause Slot'}
            </button>
        </div>` : '';

    const duty = test.on_minutes / (test.on_minutes + test.off_minutes) * 100;
    const lastSyncStr = syncedAt ? fmtTime(syncedAt) : 'No sync';
    const diffStr = ls && ls.difference_minutes != null ? 
        (ls.difference_minutes >= 0 ? `+${ls.difference_minutes.toFixed(1)}m` : `${ls.difference_minutes.toFixed(1)}m`) : '--';

    return `
    <div class="test-card status-${esc(test.status)}" onclick="openTestDetail('${esc(test.id)}')">
        <div class="test-card-inner">
            <div class="test-card-header">
                <div>
                    <span class="test-label">${esc(test.test_label)}</span>
                    <div class="test-product">${esc(test.product)}</div>
                </div>
                <span class="status-badge status-${esc(test.status)}">${esc(statusLabel(test.status))}</span>
            </div>

            <div class="test-card-counter" id="card-est-${test.id}">${hasSync ? fmtHMS(ls.machine_hours) : '--h --m --s'}</div>

            <div class="test-card-cycle">
                ${isLive && hasSync ? `
                    <span class="cycle-badge" id="card-state-${test.id}">--</span>
                    <span class="cycle-remain-sm" id="card-remain-${test.id}">--:--</span>
                ` : '<span style="color:var(--muted);font-size:12px;">' + (test.status === 'completed' ? 'Completed' : 'No sync') + '</span>'}
            </div>

            <div class="test-card-meta">
                <div class="meta-item">
                    <span class="meta-label">Operator</span>
                    <span class="meta-val">${esc(test.operator_name) || '--'}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Last Sync</span>
                    <span class="meta-val">${lastSyncStr}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Difference</span>
                    <span class="meta-val diff">${diffStr}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Next Sync</span>
                    <span class="meta-val" id="card-next-${test.id}">${isLive && hasSync ? '...' : '--'}</span>
                </div>
            </div>

            <div class="test-card-progress">
                <div class="progress-bar-wrap">
                    <div class="progress-bar-fill" style="width:${hasSync ? Math.min(ls.machine_hours/test.target_hours*100,100).toFixed(1) : 0}%"></div>
                </div>
                <span class="progress-label">${hasSync ? fmtHM(ls.machine_hours) : '0h'} / ${test.target_hours}h &nbsp;·&nbsp; ${test.on_minutes}m ON / ${test.off_minutes}m OFF</span>
            </div>

            ${pauseBtnHtml}
        </div>
    </div>`;
}

async function openTestDetail(id) {
    // Find in cache first, then fetch fresh
    currentDetailTest = liveTestData.find(t => t.id === id) || null;
    try {
        currentDetailTest = await api.getLifeTest(id);
        // normalize synced_at alias
        if (currentDetailTest.last_sync) {
            currentDetailTest.last_sync.syncedAt = currentDetailTest.last_sync.synced_at;
        }
        liveTestData = liveTestData.map(t => t.id === id ? currentDetailTest : t);
    } catch(err) {
        showToast('Could not load test detail: ' + err.message, 'error');
        return;
    }

    const test = currentDetailTest;
    const user = api.user;
    const isOp = user.role === 'operator' || user.role === 'admin';

    // Switch to detail section
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById('detailSection').classList.add('active');

    setText('detailTitle', `${test.test_label} — ${test.product}`);
    const badge = document.getElementById('detailStatusBadge');
    if (badge) { badge.textContent = statusLabel(test.status); badge.className = `status-badge status-${test.status}`; }

    // Meta info
    const metaEl = document.getElementById('detailMeta');
    if (metaEl) {
        const duty = (test.on_minutes / (test.on_minutes + test.off_minutes) * 100).toFixed(0);
        const isRunning = test.status === 'running';

        // Completed Date: "TBD" if still running, actual date once completed
        const completedDateStr = test.completed_at
            ? fmtDateTime(test.completed_at)
            : '<span style="color:var(--muted)">TBD</span>';

        // ECD: editable only once, within 7 days of initial creation (enforced server-side).
        const ecdValue = test.ecd || '';
        const st = test.ecd_status || { state: 'uncreated', editable: true, days_remaining: null, message: null };
        let ecdDisplay;
        if (isOp && isRunning && st.editable) {
            const hint = st.state === 'uncreated'
                ? 'Editable once within 7 days after you set it'
                : `Editable for ${st.days_remaining} more day${st.days_remaining === 1 ? '' : 's'} (one-time correction)`;
            ecdDisplay = `<span class="ecd-picker-wrap">
                   <input type="date" id="ecdInput" class="ecd-input" value="${esc(ecdValue)}" onchange="handleSaveECD()">
                   <span class="ecd-hint">${hint}</span>
               </span>`;
        } else if (isOp && isRunning && !st.editable) {
            // Locked for operators: show value + reason, no input rendered
            ecdDisplay = `<span class="ecd-locked-wrap">
                   <span class="meta-val">${ecdValue ? esc(ecdValue) : '<span style="color:var(--muted)">Not set</span>'}</span>
                   <span class="ecd-lock-msg">&#128274; ${esc(st.message || 'The ECD can only be modified once within 7 days of its initial creation.')}</span>
               </span>`;
        } else {
            ecdDisplay = ecdValue
                ? `<span class="meta-val">${esc(ecdValue)}</span>`
                : `<span style="color:var(--muted)">Not set</span>`;
        }

        metaEl.innerHTML = `
            <div class="meta-grid">
                <div><span class="meta-label">Product</span><span class="meta-val">${esc(test.product)}</span></div>
                <div><span class="meta-label">Datecode</span><span class="meta-val">${test.datecode ? esc(test.datecode) : '<span style="color:var(--muted)">--</span>'}</span></div>
                <div><span class="meta-label">Operator</span><span class="meta-val">${esc(test.operator_name) || '--'}</span></div>
                <div><span class="meta-label">Cycle</span><span class="meta-val">${test.on_minutes}m ON / ${test.off_minutes}m OFF</span></div>
                <div><span class="meta-label">Duty</span><span class="meta-val">${duty}%</span></div>
                <div><span class="meta-label">Target</span><span class="meta-val">${test.target_hours} h</span></div>
                <div><span class="meta-label">Started</span><span class="meta-val">${fmtDateTime(test.created_at)}</span></div>
                <div><span class="meta-label">Completed Date</span><span class="meta-val">${completedDateStr}</span></div>
                <div><span class="meta-label">ECD</span>${ecdDisplay}</div>
                <div><span class="meta-label">Slot Paused (total)</span><span class="meta-val">${fmtDuration(test.slot_total_paused_seconds)}</span></div>
            </div>`;
    }

    setText('detailTarget', test.target_hours);

    // Last sync info
    const ls = test.last_sync;
    if (ls) {
        const syncedAt = ls.synced_at;
        setText('detailLastSyncTime', fmtDateTime(syncedAt));
        setText('detailLastSyncMachine', fmtHM(ls.machine_hours) + ' (machine)');
        const diffMin = ls.difference_minutes;
        const diffEl = document.getElementById('detailDiff');
        if (diffEl) {
            diffEl.textContent = diffMin != null ? (diffMin >= 0 ? `+${diffMin.toFixed(1)} min` : `${diffMin.toFixed(1)} min`) : '--';
            diffEl.className = `sync-info-val ${diffMin > 5 ? 'diff-pos' : diffMin < -5 ? 'diff-neg' : 'diff-ok'}`;
        }
    } else {
        setText('detailLastSyncTime', 'No sync yet');
        setText('detailLastSyncMachine', '--');
        setText('detailDiff', '--');
    }

    // Show/hide action buttons based on role and status
    const isRunning     = test.status === 'running';
    const isPausedState = test.status === 'paused';
    const syncCard      = document.getElementById('syncFormCard');
    const completeCard   = document.getElementById('completeTestCard');
    const deleteCard    = document.getElementById('deleteTestCard');
    const slotPauseCard = document.getElementById('slotPauseCard');
    // Syncing/completing only while actively running (machine is off the bench while paused)
    if (syncCard)     syncCard.style.display     = (isOp && isRunning)   ? '' : 'none';
    if (completeCard)  completeCard.style.display  = (isOp && isRunning)   ? '' : 'none';
    if (deleteCard)   deleteCard.style.display    = (isOp && test.status === 'completed') ? '' : 'none';
    // Pause/Resume control for operators on running or paused slots
    if (slotPauseCard) slotPauseCard.style.display = (isOp && (isRunning || isPausedState)) ? '' : 'none';
    updateSlotPauseUI(test);

    // Counter display — frozen for completed tests; running/paused handled by tick()
    if (test.status === 'completed') {
        const frozenHours = ls ? ls.machine_hours : 0;
        setText('detailCounter', fmtHMS(frozenHours));
        const frozenPct = Math.min(frozenHours / test.target_hours * 100, 100);
        setText('detailProgress', frozenPct.toFixed(1) + '%');
        const fill = document.getElementById('detailProgressFill');
        if (fill) fill.style.width = frozenPct.toFixed(1) + '%';
        const stEl = document.getElementById('detailCycleState');
        if (stEl) { stEl.textContent = 'Completed'; stEl.className = 'cycle-state-big completed'; }
        setText('detailCycleRemain', '--');
        setText('detailNextSync', '--');
    }

    const syncResultEl = document.getElementById('syncResult');
    if (syncResultEl) syncResultEl.style.display = 'none';

    // Load sync timeline, pause history and ECD change log
    loadSyncTimeline(id);
    loadPauseHistory(id);
    loadEcdHistory(id);

    // Immediately render the live/frozen counter for running & paused slots
    if (test.status === 'running' || test.status === 'paused') tick();
}

async function loadSyncTimeline(id) {
    const tl = document.getElementById('syncTimeline');
    if (!tl) return;
    try {
        const res = await api.getSyncs(id);
        const syncs = (res.syncs || []).slice().reverse(); // newest first
        if (syncs.length === 0) { tl.innerHTML = '<p class="empty-state">No syncs recorded yet.</p>'; return; }
        tl.innerHTML = syncs.map((s, i) => {
            const diffStr = s.difference_minutes != null && i < syncs.length - 1
                ? (s.difference_minutes >= 0
                    ? `<span class="diff-pos">+${s.difference_minutes.toFixed(1)}m</span>`
                    : `<span class="diff-neg">${s.difference_minutes.toFixed(1)}m</span>`)
                : '';
            return `
            <div class="timeline-item">
                <div class="timeline-dot ${i === 0 ? 'latest' : ''}"></div>
                <div class="timeline-content">
                    <div class="timeline-time">${fmtDateTime(s.synced_at)}</div>
                    <div class="timeline-machine">Machine: <strong>${fmtHM(s.machine_hours)}</strong></div>
                    ${s.estimated_hours != null ? `<div class="timeline-est">System est: ${fmtHM(s.estimated_hours)}</div>` : ''}
                    ${diffStr ? `<div class="timeline-diff">Diff: ${diffStr}</div>` : ''}
                    ${s.notes ? `<div class="timeline-note">${esc(s.notes)}</div>` : ''}
                </div>
            </div>`;
        }).join('');
    } catch(err) {
        tl.innerHTML = '<p class="empty-state error">Could not load syncs.</p>';
    }
}

async function handleSync(e) {
    e.preventDefault();
    if (!currentDetailTest) return;
    const h = parseInt(document.getElementById('syncHours').value, 10);
    const m = parseInt(document.getElementById('syncMinutes').value, 10);
    const notes = document.getElementById('syncNotes').value;

    try {
        const res = await api.submitSync(currentDetailTest.id, h, m, notes);
        const resultEl = document.getElementById('syncResult');
        const diffMin = res.difference_minutes;
        const diffStr = diffMin >= 0 ? `+${diffMin.toFixed(1)}` : `${diffMin.toFixed(1)}`;
        if (resultEl) {
            resultEl.innerHTML = `
                <div class="sync-result-grid">
                    <div><span>Machine:</span><strong>${fmtHM(res.machine_hours)}</strong></div>
                    <div><span>System was:</span><strong>${fmtHM(res.system_estimated_hours)}</strong></div>
                    <div><span>Difference:</span><strong class="${diffMin > 5 ? 'diff-pos' : diffMin < -5 ? 'diff-neg' : 'diff-ok'}">${diffStr} min</strong></div>
                </div>`;
            resultEl.style.display = '';
        }
        showToast('Sync recorded successfully!', 'success');
        // Refresh detail view
        e.target.reset();
        await openTestDetail(currentDetailTest.id);
    } catch(err) {
        showToast('Sync failed: ' + err.message, 'error');
    }
}

async function handleCompleteTest() {
    if (!currentDetailTest) return;
    if (!confirm(`Mark "${currentDetailTest.test_label}" as completed?`)) return;
    try {
        await api.completeLifeTest(currentDetailTest.id);
        showToast('Test marked as completed.', 'success');
        await openTestDetail(currentDetailTest.id);
    } catch(err) {
        showToast(err.message, 'error');
    }
}

async function handleDeleteTest() {
    if (!currentDetailTest) return;
    if (currentDetailTest.status !== 'completed') {
        showToast('Only completed tests can be deleted.', 'error');
        return;
    }
    const label = currentDetailTest.test_label;
    if (!confirm(`Permanently delete all data for "${label}"?\n\nThis will remove the test, all sync records, and the timeline. This cannot be undone.`)) return;
    try {
        await api.deleteLifeTest(currentDetailTest.id);
        currentDetailTest = null;
        showToast(`"${label}" deleted successfully.`, 'success');
        // Return to dashboard and refresh
        showSection('dashboard', document.getElementById('navDashboard'));
    } catch(err) {
        showToast('Delete failed: ' + err.message, 'error');
    }
}

async function handleSaveECD() {
    if (!currentDetailTest) return;
    const input = document.getElementById('ecdInput');
    if (!input) return;
    const ecdDate = input.value.trim();
    try {
        const res = await api.setECD(currentDetailTest.id, ecdDate);
        if (res.action === 'edit') {
            showToast('ECD corrected — one-time edit used. The date is now locked.', 'success');
        } else if (res.action === 'create') {
            showToast('ECD set. You can correct it once within 7 days.', 'success');
        } else {
            showToast('ECD unchanged.', 'info');
        }
    } catch(err) {
        showToast('Could not save ECD: ' + err.message, 'error');
    }
    // Refresh detail so the lock state, remaining-days hint and audit trail update
    await openTestDetail(currentDetailTest.id);
}

// ==================== Per-Slot Pause ====================

/**
 * Themed dialog that requires a non-empty pause reason.
 * @returns {Promise<string|null>} the trimmed reason, or null if cancelled.
 */
function pauseReasonDialog(label) {
    return new Promise(resolve => {
        const overlay   = document.getElementById('pauseOverlay');
        if (!overlay) {   // fallback
            const r = window.prompt('Reason for pausing this slot?');
            resolve(r && r.trim() ? r.trim() : null);
            return;
        }
        const input     = document.getElementById('pauseReasonInput');
        const errEl     = document.getElementById('pauseReasonError');
        const titleEl   = document.getElementById('pauseDialogTitle');
        const okBtn     = document.getElementById('pauseConfirmBtn');
        const cancelBtn = document.getElementById('pauseCancelBtn');

        titleEl.textContent = label ? `Pause ${label}` : 'Pause Slot';
        input.value = '';
        errEl.style.display = 'none';
        overlay.style.display = 'flex';
        setTimeout(() => input.focus(), 30);

        function cleanup(result) {
            overlay.style.display = 'none';
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            overlay.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onKey);
            resolve(result);
        }
        function onOk() {
            const val = input.value.trim();
            if (!val) { errEl.style.display = ''; input.focus(); return; }  // reason is mandatory
            cleanup(val);
        }
        const onCancel   = () => cleanup(null);
        const onBackdrop = (e) => { if (e.target === overlay) cleanup(null); };
        const onKey = (e) => {
            if (e.key === 'Escape') cleanup(null);
            else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) onOk();
        };
        okBtn.addEventListener('click', onOk);
        cancelBtn.addEventListener('click', onCancel);
        overlay.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onKey);
    });
}

/** Pause a single slot after collecting a mandatory reason. Returns true if paused. */
async function doPauseSlot(id, label) {
    const reason = await pauseReasonDialog(label);
    if (reason === null) return false;   // cancelled
    try {
        await api.pauseLifeTest(id, reason);
        showToast('Slot paused — timer frozen.', 'warning');
        return true;
    } catch (err) {
        showToast('Pause failed: ' + err.message, 'error');
        return false;
    }
}

/** Resume a single slot (with confirmation). Returns true if resumed. */
async function doResumeSlot(id, label) {
    const ok = await confirmDialog({
        title: `Resume ${label}?`,
        message: 'This slot\'s timer will continue from where it stopped. The paused time is excluded from the effective testing time.',
        okText: 'Resume Slot', okClass: 'btn-resume', icon: '&#9654;'
    });
    if (!ok) return false;
    try {
        const res = await api.resumeLifeTest(id);
        const paused = res && res.total_paused_minutes != null
            ? ` Paused for ${fmtDuration(res.total_paused_minutes * 60)}.` : '';
        showToast('Slot resumed — timer continues.' + paused, 'success');
        return true;
    } catch (err) {
        showToast('Resume failed: ' + err.message, 'error');
        return false;
    }
}

/** Pause/Resume toggle from a dashboard card. */
async function handleCardPauseToggle(id, event) {
    if (event) event.stopPropagation();   // don't open the detail view
    const test = liveTestData.find(t => t.id === id);
    if (!test) return;
    const changed = test.status === 'paused'
        ? await doResumeSlot(id, test.test_label)
        : await doPauseSlot(id, test.test_label);
    if (changed) await loadLifeTests();
}

/** Pause/Resume toggle from the detail view. */
async function handleSlotPauseToggle() {
    if (!currentDetailTest) return;
    const { id, test_label } = currentDetailTest;
    const changed = currentDetailTest.status === 'paused'
        ? await doResumeSlot(id, test_label)
        : await doPauseSlot(id, test_label);
    if (changed) await openTestDetail(id);
}

/** Update the detail-view pause button label/style based on slot status. */
function updateSlotPauseUI(test) {
    const btn = document.getElementById('slotPauseBtn');
    if (!btn) return;
    if (test.status === 'paused') {
        btn.innerHTML = '&#9654; Resume This Slot';
        btn.className  = 'btn btn-resume btn-full';
    } else {
        btn.innerHTML = '&#9208; Pause This Slot';
        btn.className  = 'btn btn-warning btn-full';
    }
}

/** Load and render the per-slot pause history; also surfaces the active pause banner. */
async function loadPauseHistory(id) {
    const list = document.getElementById('pauseHistoryList');
    if (!list) return;
    try {
        const res  = await api.getTestPauseLogs(id);
        const logs = res.logs || [];

        // Active-pause banner inside the pause control card
        const active   = logs.find(l => !l.resume_time);
        const statusEl = document.getElementById('slotPauseStatus');
        if (statusEl) {
            statusEl.innerHTML = active
                ? `<div class="slot-pause-active"><strong>&#9208; Paused</strong> since ${fmtDateTime(active.pause_time)}
                     <br><span class="slot-pause-reason">Reason: ${esc(active.reason)}</span></div>`
                : '';
        }

        if (logs.length === 0) { list.innerHTML = '<p class="empty-state">No pauses recorded.</p>'; return; }
        list.innerHTML = logs.map(l => {
            const ongoing = !l.resume_time;
            const durSec  = l.total_paused_minutes != null
                ? l.total_paused_minutes * 60
                : (ongoing ? (Date.now() - toUtcMs(l.pause_time)) / 1000 : 0);
            const operator = l.operator_name || l.user_full_name;
            return `
            <div class="timeline-item">
                <div class="timeline-dot ${ongoing ? 'latest' : ''}"></div>
                <div class="timeline-content">
                    <div class="timeline-time">${fmtDateTime(l.pause_time)}${ongoing ? '<span class="pause-ongoing-tag">ONGOING</span>' : ''}</div>
                    <div class="timeline-machine">Duration: <strong>${ongoing ? 'in progress' : fmtDuration(durSec)}</strong></div>
                    ${l.resume_time ? `<div class="timeline-est">Resumed: ${fmtDateTime(l.resume_time)}</div>` : ''}
                    <div class="timeline-reason"><strong>Reason:</strong> ${esc(l.reason)}</div>
                    ${operator ? `<div class="timeline-est">Operator: ${esc(operator)}</div>` : ''}
                </div>
            </div>`;
        }).join('');
    } catch (err) {
        list.innerHTML = '<p class="empty-state error">Could not load pause history.</p>';
    }
}

/** Load and render the ECD create/edit audit trail for a slot. */
async function loadEcdHistory(id) {
    const list = document.getElementById('ecdHistoryList');
    if (!list) return;
    try {
        const res  = await api.getEcdLogs(id);
        const logs = res.logs || [];
        if (logs.length === 0) { list.innerHTML = '<p class="empty-state">No ECD set yet.</p>'; return; }
        list.innerHTML = logs.map((l, i) => {
            const isCreate = l.action === 'create';
            const label = isCreate ? 'Initial ECD created' : 'ECD corrected (one-time edit)';
            const change = isCreate
                ? `Set to <strong>${esc(l.new_ecd)}</strong>`
                : `<strong>${esc(l.old_ecd || '—')}</strong> &rarr; <strong>${esc(l.new_ecd)}</strong>`;
            return `
            <div class="timeline-item">
                <div class="timeline-dot ${i === 0 ? 'latest' : ''}"></div>
                <div class="timeline-content">
                    <div class="timeline-time">${fmtDateTime(l.changed_at)}
                        <span class="ecd-action-tag ${isCreate ? 'create' : 'edit'}">${isCreate ? 'CREATE' : 'EDIT'}</span></div>
                    <div class="timeline-machine">${label}</div>
                    <div class="timeline-reason">${change}</div>
                    ${l.operator_name ? `<div class="timeline-est">By: ${esc(l.operator_name)}</div>` : ''}
                </div>
            </div>`;
        }).join('');
    } catch (err) {
        list.innerHTML = '<p class="empty-state error">Could not load ECD history.</p>';
    }
}

// ==================== New Life Test ====================

function applyPreset() {
    const preset = document.getElementById('ntCyclePreset').value;
    const customRow = document.getElementById('customCycle');
    if (preset === 'custom') {
        customRow.style.display = '';
    } else {
        customRow.style.display = 'none';
        if (preset === 'ul') {
            document.getElementById('ntOnMin').value  = 8;
            document.getElementById('ntOffMin').value = 2;
        } else if (preset === 'iec') {
            document.getElementById('ntOnMin').value  = 14;
            document.getElementById('ntOffMin').value = 0.5;
        }
    }
}

async function handleCreateTest(e) {
    e.preventDefault();
    const preset = document.getElementById('ntCyclePreset').value;
    let onMin  = parseFloat(document.getElementById('ntOnMin').value)  || 8;
    let offMin = parseFloat(document.getElementById('ntOffMin').value) || 2;
    if (preset === 'ul')  { onMin = 8;    offMin = 2;   }
    if (preset === 'iec') { onMin = 14;   offMin = 0.5; }

    const initH = parseInt(document.getElementById('ntInitHours').value,   10) || 0;
    const initM = parseInt(document.getElementById('ntInitMinutes').value,  10) || 0;

    const payload = {
        test_label:             document.getElementById('ntLabel').value.trim(),
        product:                document.getElementById('ntProduct').value.trim(),
        datecode:               document.getElementById('ntDatecode').value.trim(),
        on_minutes:             onMin,
        off_minutes:            offMin,
        target_hours:           parseInt(document.getElementById('ntTarget').value, 10),
        initial_machine_hours:  initH + initM / 60.0,
        notes:                  document.getElementById('ntNotes').value.trim()
    };

    try {
        await api.createLifeTest(payload);
        showToast(`Life test ${payload.test_label} created!`, 'success');
        e.target.reset();
        showSection('dashboard', document.getElementById('navDashboard'));
    } catch(err) {
        showToast('Error: ' + err.message, 'error');
    }
}

// ==================== Reports ====================

async function loadReports() {
    const tbody = document.getElementById('reportsTable');
    if (!tbody) return;
    try {
        const res = await api.getSyncQualityReport();
        const rows = res.report || [];
        if (rows.length === 0) { tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No data yet.</td></tr>'; return; }
        tbody.innerHTML = rows.map(r => `
            <tr>
                <td>${esc(r.test_label)}</td>
                <td>${esc(r.product)}</td>
                <td><span class="status-badge status-${esc(r.status)}">${esc(statusLabel(r.status))}</span></td>
                <td>${r.total_syncs ?? 0}</td>
                <td>${r.avg_diff_minutes != null ? r.avg_diff_minutes.toFixed(2) + ' min' : '--'}</td>
                <td>${r.max_diff_minutes != null ? r.max_diff_minutes.toFixed(2) + ' min' : '--'}</td>
            </tr>`).join('');
    } catch(err) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state error">${err.message}</td></tr>`;
    }
}

// ==================== Settings ====================

function loadSettings() {
    const user = api.user;
    setText('settingsName',  user.full_name || '--');
    setText('settingsEmail', user.email     || '--');
    setText('settingsRole',  user.role      || '--');
    const card = document.getElementById('syncIntervalCard');
    if (card) card.style.display = user.role === 'admin' ? '' : 'none';
}

async function handleIntervalUpdate(e) {
    e.preventDefault();
    const min = parseInt(document.getElementById('intervalInput').value, 10);
    try {
        await api.setUploadInterval(min);
        showToast('Interval updated.', 'success');
    } catch(err) {
        showToast(err.message, 'error');
    }
}

// ==================== Init ====================

(async () => {
    if (api.token && api.user) {
        try {
            await api.verifyToken();
            showDashboard();
        } catch (_) {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('user');
        }
    }
})();
