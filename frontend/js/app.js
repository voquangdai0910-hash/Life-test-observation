// Version check - force refresh if old version is cached
const APP_VERSION = '2.1.0';
const CACHED_VERSION = localStorage.getItem('appVersion');
if (CACHED_VERSION !== APP_VERSION) {
    localStorage.setItem('appVersion', APP_VERSION);
    if (CACHED_VERSION) {
        // Old version was cached, reload to get new one
        location.reload(true);
    }
}

// ==================== Utility Functions ====================

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.textContent = message;
        toast.className = `toast ${type}`;
        toast.style.display = 'block';
        
        setTimeout(() => {
            toast.style.display = 'none';
        }, 3000);
    }
}

function showStatus(elementId, message, type = 'info') {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = message;
        element.className = `status-message ${type}`;
        element.style.display = 'block';
    }
}

function formatDateTime(dateString) {
    if (!dateString) return '--';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

function formatDate(dateString) {
    if (!dateString) return '--';
    return new Date(dateString).toLocaleDateString();
}

function formatTime(dateString) {
    if (!dateString) return '--:--';
    return new Date(dateString).toLocaleTimeString();
}

function getTimeUntil(targetDate) {
    const now = new Date();
    const target = new Date(targetDate);
    const diff = target - now;
    
    if (diff < 0) return 'Overdue';
    
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    
    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
}

function closeModal(event) {
    if (event && event.target.id !== 'detailsModal') return;
    document.getElementById('detailsModal').classList.remove('show');
}

// ==================== Tab and Section Navigation ====================

function switchTab(tab) {
    // Remove active class from all tabs
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('active');
    });
    
    // Add active class to selected tab
    document.getElementById(tab + 'Tab').classList.add('active');
    event.target.classList.add('active');
}

function showSection(section) {
    event.preventDefault();
    
    // Remove active from all sections
    document.querySelectorAll('.section').forEach(el => {
        el.classList.remove('active');
    });
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.remove('active');
    });
    
    // Add active to selected section
    document.getElementById(section + 'Section').classList.add('active');
    
    // Add active to nav item
    event.target.closest('.nav-item').classList.add('active');
    
    // Load section data
    loadSectionData(section);
}

// ==================== Authentication Functions ====================

async function handleLogin(event) {
    event.preventDefault();
    
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    
    try {
        const response = await api.login(email, password);
        
        api.setToken(response.access_token);
        api.setUser(response.user);
        
        showToast('Login successful!', 'success');
        showDashboard();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleRegister(event) {
    event.preventDefault();
    
    const name = document.getElementById('registerName').value;
    const email = document.getElementById('registerEmail').value;
    const password = document.getElementById('registerPassword').value;
    const role = document.getElementById('registerRole').value;
    
    try {
        const response = await api.register(email, password, name, role);
        
        api.setToken(response.access_token);
        api.setUser(response.user);
        
        showToast('Registration successful!', 'success');
        showDashboard();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function handleLogout() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
    location.reload();
}

// ==================== View Management ====================

function showDashboard() {
    document.getElementById('loginView').style.display = 'none';
    document.getElementById('dashboardView').style.display = 'flex';
    
    // Update user info
    const user = api.user;
    document.getElementById('userName').textContent = user.full_name || user.email;
    document.getElementById('userRole').textContent = `(${user.role.replace('_', ' ')})`;
    
    // Show/hide sections based on role
    const isOperator = user.role === 'operator';
    const isAccessPerson = user.role === 'access_person';
    const isAdmin = user.role === 'admin';
    
    document.getElementById('uploadNavBtn').style.display = isOperator ? 'flex' : 'none';
    document.getElementById('testingNavBtn').style.display = isOperator ? 'flex' : 'none';
    document.getElementById('reportsNavBtn').style.display = isAccessPerson || isAdmin ? 'flex' : 'none';
    document.getElementById('settingsNavBtn').style.display = isAdmin ? 'flex' : 'none';
    
    // Show/hide dashboard stats based on role
    document.getElementById('operatorStats').style.display = isOperator ? 'grid' : 'none';
    document.getElementById('accessPersonStats').style.display = isAccessPerson || isAdmin ? 'grid' : 'none';
    
    // Load ON hours for operators
    if (isOperator) {
        loadOnHoursProgress();
    }
    
    loadDashboard();
}

// ==================== Dashboard Data Loading ====================

async function loadDashboard() {
    try {
        const summary = await api.getDashboardSummary();
        
        if (api.user.role === 'operator') {
            document.getElementById('myUploadsCount').textContent = summary.my_uploads;
            document.getElementById('uploadInterval').textContent = formatInterval(summary.upload_interval_minutes);
            
            // Update next deadline
            if (summary.next_upload_deadline) {
                document.getElementById('nextDeadline').textContent = getTimeUntil(summary.next_upload_deadline);
            }
        } else {
            const stats = summary.stats;
            document.getElementById('totalUploads').textContent = stats.total_uploads;
            document.getElementById('activeTests').textContent = stats.active_tests;
            document.getElementById('completedTests').textContent = stats.completed_tests;
            document.getElementById('operatorsCount').textContent = stats.operators_count;
            
            if (stats.last_upload) {
                document.getElementById('lastUploadTime').textContent = formatTime(stats.last_upload);
            }
            if (stats.next_scheduled_upload) {
                document.getElementById('nextScheduledUpload').textContent = getTimeUntil(stats.next_scheduled_upload);
            }
        }
        
        loadActivityLog();
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

async function loadActivityLog() {
    try {
        const activityLog = document.getElementById('activityLog');
        activityLog.innerHTML = '';
        
        if (api.user.role === 'operator') {
            const data = await api.getMyUploads(5);
            
            if (data.uploads.length === 0) {
                activityLog.innerHTML = '<p class="empty-state">No uploads yet</p>';
                return;
            }
            
            data.uploads.forEach(upload => {
                const item = document.createElement('div');
                item.className = 'activity-item';
                item.innerHTML = `
                    <div class="activity-icon">📤</div>
                    <div class="activity-text">
                        <div class="activity-title">Uploaded: <strong>${upload.test_name}</strong></div>
                        <div class="activity-time">${formatDateTime(upload.uploaded_at)}</div>
                    </div>
                `;
                activityLog.appendChild(item);
            });
        } else {
            const data = await api.getAllUploads(5);
            
            if (data.uploads.length === 0) {
                activityLog.innerHTML = '<p class="empty-state">No uploads yet</p>';
                return;
            }
            
            data.uploads.forEach(upload => {
                const item = document.createElement('div');
                item.className = 'activity-item';
                item.innerHTML = `
                    <div class="activity-icon">📤</div>
                    <div class="activity-text">
                        <div class="activity-title"><strong>${upload.test_name}</strong> uploaded</div>
                        <div class="activity-time">${formatDateTime(upload.uploaded_at)}</div>
                    </div>
                `;
                activityLog.appendChild(item);
            });
        }
    } catch (error) {
        console.error('Error loading activity log:', error);
    }
}

function formatInterval(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours > 0) {
        return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
    }
    return `${mins}m`;
}

// ==================== Section Data Loading ====================

async function loadSectionData(section) {
    switch (section) {
        case 'upload':
            loadUploadSection();
            break;
        case 'testing':
            loadTestingSection();
            break;
        case 'reports':
            loadReportsSection();
            break;
        case 'settings':
            loadSettingsSection();
            break;
    }
}

async function loadUploadSection() {
    try {
        const interval = await api.getUploadInterval();
        const intervalText = `Every ${formatInterval(interval.interval_minutes)}`;
        const formattedInterval = formatInterval(interval.interval_minutes);
        
        // Safely update elements only if they exist
        const deadlineEl = document.getElementById('deadlineInfo');
        if (deadlineEl) deadlineEl.textContent = intervalText;
        
        const intervalEl = document.getElementById('uploadInterval');
        if (intervalEl) intervalEl.textContent = formattedInterval;
    } catch (error) {
        console.error('Error loading upload interval:', error);
    }
}

async function loadTestingSection() {
    try {
        // Load ON hours progress first
        await loadOnHoursProgress();
        
        const data = await api.getActiveTesting();
        const testList = document.getElementById('activeTestsList');
        testList.innerHTML = '';
        
        if (data.active_tests.length === 0) {
            testList.innerHTML = '<p class="empty-state">No active tests</p>';
            return;
        }
        
        data.active_tests.forEach(test => {
            const item = document.createElement('div');
            item.className = 'test-item';
            
            const startTime = new Date(test.start_time);
            const now = new Date();
            const duration = Math.floor((now - startTime) / 60000);
            
            item.innerHTML = `
                <div class="test-info">
                    <div class="test-name">${test.test_name}</div>
                    <div class="test-time">Started: ${formatTime(test.start_time)} | Duration: ${duration} min | Operator: ${test.users?.full_name || 'Unknown'}</div>
                </div>
                <div class="test-actions">
                    <button class="btn btn-primary" onclick="handleEndTest('${test.id}')">End Test</button>
                </div>
            `;
            testList.appendChild(item);
        });
    } catch (error) {
        console.error('Error loading testing section:', error);
    }
}

async function loadReportsSection() {
    try {
        const data = await api.getAllUploads(100);
        const table = document.getElementById('uploadsTable');
        table.innerHTML = '';
        
        if (data.uploads.length === 0) {
            table.innerHTML = '<tr class="empty-row"><td colspan="5" class="empty-state">No uploads yet</td></tr>';
            return;
        }
        
        data.uploads.forEach(upload => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${upload.test_name}</td>
                <td>${upload.operator_id}</td>
                <td>${formatDateTime(upload.uploaded_at)}</td>
                <td>${upload.description || '-'}</td>
                <td>
                    <button class="btn btn-primary" onclick="viewUploadDetails('${upload.id}')">View</button>
                </td>
            `;
            table.appendChild(row);
        });
    } catch (error) {
        console.error('Error loading reports section:', error);
    }
}

async function loadSettingsSection() {
    try {
        // Update account info
        const user = api.user;
        document.getElementById('settingsName').textContent = user.full_name;
        document.getElementById('settingsEmail').textContent = user.email;
        document.getElementById('settingsRole').textContent = user.role.replace('_', ' ');
        
        // Show interval settings only for admin
        if (api.user.role === 'admin') {
            document.getElementById('uploadIntervalSettings').style.display = 'block';
            const interval = await api.getUploadInterval();
            document.getElementById('intervalInput').value = interval.interval_minutes;
            updateIntervalPreview(interval.interval_minutes);
        }
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

function updateIntervalPreview(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    const text = hours > 0 
        ? (mins > 0 ? `${hours} hours and ${mins} minutes` : `${hours} hours`)
        : `${mins} minutes`;
    document.getElementById('previewInterval').textContent = text;
}

// ==================== Form Handlers ====================

async function handleDataUpload(event) {
    event.preventDefault();
    
    const testName = document.getElementById('testName').value;
    const description = document.getElementById('testDescription').value;
    const cyclePattern = document.getElementById('cyclePattern').value;
    const dataStr = document.getElementById('testData').value;
    
    try {
        // Parse JSON data
        const data = JSON.parse(dataStr);
        
        // Add metadata
        const uploadData = {
            ...data,
            cycle_pattern: cyclePattern,
            upload_timestamp: new Date().toISOString()
        };
        
        await api.uploadData(testName, description, uploadData);
        
        showStatus('uploadStatus', 'Data uploaded successfully and ON hours calculated!', 'success');
        document.getElementById('uploadForm').reset();
        
        showToast('Upload successful! ON hours calculated.', 'success');
        
        // Reload activity log and ON hours progress
        loadActivityLog();
        loadOnHoursProgress();
    } catch (error) {
        if (error instanceof SyntaxError) {
            showStatus('uploadStatus', 'Invalid JSON format', 'error');
        } else {
            showStatus('uploadStatus', error.message, 'error');
        }
        showToast(error.message, 'error');
    }
}

async function loadOnHoursProgress() {
    try {
        const response = await api.request('GET', '/uploads/on-hours');
        const progress = response.progress;
        
        // Update display
        document.getElementById('accumulatedOnHours').textContent = progress.cumulative_on_hours.toFixed(2);
        document.getElementById('onHoursPercent').textContent = progress.progress_percent.toFixed(1);
        document.getElementById('remainingOnHours').textContent = progress.remaining_hours.toFixed(2);
        
        const progressFill = document.getElementById('onHoursProgressFill');
        progressFill.style.width = progress.progress_percent + '%';
        
        // Show congratulations if complete
        if (progress.is_complete) {
            showToast('🎉 Test target reached! Congratulations!', 'success');
        }
    } catch (error) {
        console.error('Error loading ON hours progress:', error);
    }
}

async function handleStartTest(event) {
    event.preventDefault();
    
    const testName = document.getElementById('testNameInput').value;
    const targetHours = document.getElementById('testTargetHours').value;
    const notes = document.getElementById('testNotesInput').value;
    
    try {
        await api.startTesting(testName, notes);
        
        showToast('Test started! Target: ' + targetHours + ' hours', 'success');
        document.getElementById('startTestForm').reset();
        loadTestingSection();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleEndTest(sessionId) {
    if (!confirm('Are you sure you want to end this test?')) return;
    
    try {
        await api.endTesting(sessionId);
        showToast('Test ended!', 'success');
        loadTestingSection();
        loadActivityLog();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleIntervalUpdate(event) {
    event.preventDefault();
    
    const interval = parseInt(document.getElementById('intervalInput').value);
    
    try {
        await api.setUploadInterval(interval);
        showToast('Upload interval updated!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== Detail View ====================

function viewUploadDetails(uploadId) {
    const modal = document.getElementById('detailsModal');
    
    // Note: In a real app, you'd fetch the full details from the API
    const body = document.getElementById('modalBody');
    body.innerHTML = `
        <p>Upload ID: ${uploadId}</p>
        <p>This is a placeholder for detailed upload information.</p>
    `;
    
    modal.classList.add('show');
}

// ==================== Initialize App ====================

async function initializeApp() {
    // Check if user is logged in
    if (api.token && api.user) {
        try {
            await api.verifyToken();
            showDashboard();
        } catch (error) {
            // Token invalid, show login
            showToast('Session expired. Please login again.', 'info');
        }
    }
}

// Update interval preview when input changes
document.addEventListener('DOMContentLoaded', () => {
    const intervalInput = document.getElementById('intervalInput');
    if (intervalInput) {
        intervalInput.addEventListener('change', (e) => {
            updateIntervalPreview(parseInt(e.target.value));
        });
    }
    
    // Initialize data builder for time series input
    initializeDataBuilder();
    
    // Initialize app
    initializeApp();
});

// Refresh dashboard periodically for access person
setInterval(() => {
    if (document.getElementById('dashboardView').style.display !== 'none' && 
        document.getElementById('dashboardSection').classList.contains('active') &&
        api.user && api.user.role !== 'operator') {
        loadDashboard();
    }
}, 30000); // Every 30 seconds

// ==================== Data Builder for Time Series ====================

let builtDataPoints = [];

function initializeDataBuilder() {
    // Toggle data builder visibility
    const toggleBtn = document.getElementById('toggleDataBuilder');
    const builderDiv = document.getElementById('dataBuilder');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            builderDiv.style.display = builderDiv.style.display === 'none' ? 'block' : 'none';
        });
    }
    
    // Add data point button
    const addBtn = document.getElementById('addDataPoint');
    if (addBtn) {
        addBtn.addEventListener('click', (e) => {
            e.preventDefault();
            addDataPoint();
        });
    }
    
    // Insert built data button
    const insertBtn = document.getElementById('insertBuiltData');
    if (insertBtn) {
        insertBtn.addEventListener('click', (e) => {
            e.preventDefault();
            insertBuiltDataToTextarea();
        });
    }
    
    // Clear built data button
    const clearBtn = document.getElementById('clearBuiltData');
    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.preventDefault();
            builtDataPoints = [];
            renderDataPoints();
        });
    }
    
    // Insert sample data button
    const sampleBtn = document.getElementById('insertSampleData');
    if (sampleBtn) {
        sampleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            insertSampleData();
        });
    }
    
    // Allow Enter key to add data point
    const timeInput = document.getElementById('builderTime');
    if (timeInput) {
        timeInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addDataPoint();
            }
        });
    }
}

    function toggleDataBuilder() {
        const builder = document.getElementById('dataBuilder');
        if (builder) {
            builder.style.display = builder.style.display === 'none' ? 'block' : 'none';
        }
    }

    function clearBuiltDataFunc() {
        builtDataPoints = [];
        renderDataPoints();
        showToast('Data points cleared', 'info');
    }
function addDataPoint() {
    const timeInput = document.getElementById('builderTime');
    const stateSelect = document.getElementById('builderState');
    
    if (!timeInput.value) {
        showToast('Please enter a time', 'error');
        return;
    }
    
    const today = new Date().toISOString().split('T')[0];
    const timestamp = `${today}T${timeInput.value}:00Z`;
    const state = stateSelect.value;
    
    builtDataPoints.push({ timestamp, state });
    
    // Clear input
    timeInput.value = '';
    timeInput.focus();
    
    renderDataPoints();
    showToast('Data point added', 'success');
}

function renderDataPoints() {
    const listDiv = document.getElementById('dataPointsList');
    if (builtDataPoints.length === 0) {
        listDiv.innerHTML = '<div class="empty-data-list">No data points yet. Add one above!</div>';
        return;
    }
    listDiv.innerHTML = builtDataPoints.map((point, idx) => {
        const time = new Date(point.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        const isOn = point.state === 'ON';
        return `<div class="data-point-item">
                    <span class="data-point-time">${time}</span>
                    <span class="data-point-state ${isOn ? 'on' : 'off'}">${point.state}</span>
                    <button type="button" class="data-point-remove" onclick="removeDataPoint(${idx})" title="Remove">&times;</button>
                </div>`;
    }).join('');
}

function removeDataPoint(index) {
    builtDataPoints.splice(index, 1);
    renderDataPoints();
}

function insertBuiltDataToTextarea() {
    if (builtDataPoints.length === 0) {
        showToast('Please add at least one data point', 'error');
        return;
    }
    const jsonData = { data_points: builtDataPoints };
    const textarea = document.getElementById('testData');
    textarea.value = JSON.stringify(jsonData, null, 2);
    const builder = document.getElementById('dataBuilder');
    if (builder) builder.style.display = 'none';
    showToast('Data inserted! Ready to upload.', 'success');
    builtDataPoints = [];
    renderDataPoints();
}

function insertSampleData() {
    const now = new Date();
    const sampleData = {
        data_points: [
            { timestamp: new Date(now.getTime() - 8 * 60000).toISOString(), state: 'ON' },
            { timestamp: new Date(now.getTime() - 2 * 60000).toISOString(), state: 'OFF' },
            { timestamp: new Date(now.getTime()).toISOString(), state: 'ON' }
        ]
    };
    const textarea = document.getElementById('testData');
    textarea.value = JSON.stringify(sampleData, null, 2);
    showToast('Sample data inserted!', 'success');
}

function toggleDataBuilder() {
    const builder = document.getElementById('dataBuilder');
    if (builder) {
        builder.style.display = builder.style.display === 'none' ? 'block' : 'none';
    }
}

function clearBuiltDataFunc() {
    builtDataPoints = [];
    renderDataPoints();
    showToast('Data points cleared', 'info');
}
