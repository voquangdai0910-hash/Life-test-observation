// Dynamic API base URL detection
function getAPIBaseURL() {
    const host = window.location.hostname;
    const proto = window.location.protocol;
    if (host.includes('.app.github.dev')) {
        return `${proto}//${host.replace('-8081.', '-8000.').replace('-8001.', '-8000.')}/api`;
    }
    return `${proto}//localhost:8000/api`;
}

const API_BASE_URL = getAPIBaseURL();

class LabDataAPI {
    constructor() {
        this.token = localStorage.getItem('auth_token') || null;
        this.user = JSON.parse(localStorage.getItem('user') || 'null');
    }

    setToken(token) { this.token = token; localStorage.setItem('auth_token', token); }
    setUser(user) { this.user = user; localStorage.setItem('user', JSON.stringify(user)); }

    getHeaders(auth = true) {
        const h = { 'Content-Type': 'application/json' };
        if (auth && this.token) h['Authorization'] = `Bearer ${this.token}`;
        return h;
    }

    async request(method, endpoint, data = null, auth = true) {
        try {
            const opts = { method, headers: this.getHeaders(auth) };
            if (data) opts.body = JSON.stringify(data);
            const res = await fetch(`${API_BASE_URL}${endpoint}`, opts);
            if (!res.ok) {
                if (res.status === 401) {
                    localStorage.removeItem('auth_token');
                    localStorage.removeItem('user');
                    window.location.reload();
                }
                // Error body may not be JSON (proxy 502/504 HTML, empty body) —
                // don't let JSON.parse mask the real status code.
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            return await res.json();
        } catch (e) {
            console.error('API Error:', e);
            throw e;
        }
    }

    // ── Auth ──
    register(email, password, fullName) {
        return this.request('POST', '/auth/register', { email, password, full_name: fullName }, false);
    }
    login(email, password) {
        return this.request('POST', '/auth/login', { email, password }, false);
    }
    verifyToken() { return this.request('GET', '/auth/verify'); }
    changePassword(current, next) {
        return this.request('POST', '/auth/change-password', { current_password: current, new_password: next });
    }

    // ── Life Tests ──
    createLifeTest(payload) { return this.request('POST', '/life-tests', payload); }
    getLifeTests(status = '') {
        return this.request('GET', `/life-tests${status ? '?test_status=' + status : ''}`);
    }
    getLifeTest(id) { return this.request('GET', `/life-tests/${id}`); }
    completeLifeTest(id) { return this.request('PATCH', `/life-tests/${id}/complete`); }
    deleteLifeTest(id)   { return this.request('DELETE', `/life-tests/${id}`); }
    setECD(id, ecdDate)  { return this.request('PATCH', `/life-tests/${id}/ecd`, { ecd_date: ecdDate }); }
    getEcdLogs(id)       { return this.request('GET', `/life-tests/${id}/ecd-logs`); }

    // ── Syncs ──
    submitSync(lifeTestId, machineHours, machineMinutes, notes = '') {
        return this.request('POST', `/life-tests/${lifeTestId}/sync`, {
            machine_hours: machineHours,
            machine_minutes: machineMinutes,
            notes
        });
    }
    getSyncs(lifeTestId) { return this.request('GET', `/life-tests/${lifeTestId}/syncs`); }

    // ── Per-Slot Pause ──
    pauseLifeTest(id, reason)  { return this.request('POST', `/life-tests/${id}/pause`,  { reason }); }
    resumeLifeTest(id, notes = '') { return this.request('POST', `/life-tests/${id}/resume`, { notes }); }
    getTestPauseLogs(id, limit = 100) { return this.request('GET', `/life-tests/${id}/pause-logs?limit=${limit}`); }

    // ── Reports ──
    getSyncQualityReport() { return this.request('GET', '/reports/sync-quality'); }

    // ── System Pause ──
    getSystemState() { return this.request('GET', '/system/state'); }
    pauseSystem(notes = '')  { return this.request('POST', '/system/pause',  { notes }); }
    resumeSystem(notes = '') { return this.request('POST', '/system/resume', { notes }); }
    getPauseLogs(limit = 100) { return this.request('GET', `/system/pause-logs?limit=${limit}`); }

    // ── Config (legacy) ──
    getUploadInterval() { return this.request('GET', '/config/upload-interval'); }
    setUploadInterval(m) { return this.request('POST', '/config/upload-interval', { interval_minutes: m }); }

    // ── Admin: User Management ──
    listUsers() { return this.request('GET', '/admin/users'); }
    createUser(payload) { return this.request('POST', '/admin/users', payload); }
    setUserRole(id, role) { return this.request('PATCH', `/admin/users/${id}/role`, { role }); }
    deleteUser(id) { return this.request('DELETE', `/admin/users/${id}`); }
}

const api = new LabDataAPI();
