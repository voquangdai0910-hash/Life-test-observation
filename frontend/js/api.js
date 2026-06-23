// API Configuration - Dynamic URL detection for local and GitHub Codespaces
function getAPIBaseURL() {
    const host = window.location.hostname;
    const protocol = window.location.protocol;
    
    // GitHub Codespaces tunnel (port 8000 for API)
    if (host.includes('.app.github.dev')) {
        return `${protocol}//${host.replace('-8001.', '-8000.')}/api`;
    }
    
    // Local development
    return `${protocol}//localhost:8000/api`;
}

const API_BASE_URL = getAPIBaseURL();

class LabDataAPI {
    constructor() {
        this.token = localStorage.getItem('auth_token') || null;
        this.user = JSON.parse(localStorage.getItem('user') || 'null');
    }
    
    setToken(token) {
        this.token = token;
        localStorage.setItem('auth_token', token);
    }
    
    setUser(user) {
        this.user = user;
        localStorage.setItem('user', JSON.stringify(user));
    }
    
    getHeaders(includeAuth = true) {
        const headers = {
            'Content-Type': 'application/json',
        };
        
        if (includeAuth && this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        
        return headers;
    }
    
    async request(method, endpoint, data = null, includeAuth = true) {
        try {
            const options = {
                method,
                headers: this.getHeaders(includeAuth),
            };
            
            if (data) {
                options.body = JSON.stringify(data);
            }
            
            const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
            
            if (!response.ok) {
                if (response.status === 401) {
                    // Clear auth and redirect to login
                    localStorage.removeItem('auth_token');
                    localStorage.removeItem('user');
                    window.location.reload();
                }
                
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
    
    // ==================== Authentication ====================
    
    async register(email, password, fullName, role) {
        return this.request('POST', '/auth/register', {
            email,
            password,
            full_name: fullName,
            role
        }, false);
    }
    
    async login(email, password) {
        return this.request('POST', '/auth/login', {
            email,
            password
        }, false);
    }
    
    async verifyToken() {
        return this.request('GET', '/auth/verify');
    }
    
    // ==================== Data Upload ====================
    
    async uploadData(testName, description, data) {
        return this.request('POST', '/uploads/data', {
            test_name: testName,
            description,
            data
        });
    }
    
    async getMyUploads(limit = 50) {
        return this.request('GET', `/uploads/my-uploads?limit=${limit}`);
    }
    
    async getAllUploads(limit = 100) {
        return this.request('GET', `/uploads/all?limit=${limit}`);
    }
    
    // ==================== Upload Interval ====================
    
    async getUploadInterval() {
        return this.request('GET', '/config/upload-interval');
    }
    
    async setUploadInterval(intervalMinutes) {
        return this.request('POST', '/config/upload-interval', {
            interval_minutes: intervalMinutes
        });
    }
    
    // ==================== Testing Time ====================
    
    async startTesting(testName, notes) {
        return this.request('POST', '/testing/start', {
            test_name: testName,
            notes
        });
    }
    
    async endTesting(sessionId) {
        return this.request('POST', `/testing/end/${sessionId}`);
    }
    
    async getActiveTesting() {
        return this.request('GET', '/testing/active');
    }
    
    async getTestingHistory(operatorId = null, limit = 50) {
        let endpoint = `/testing/history?limit=${limit}`;
        if (operatorId) {
            endpoint += `&operator_id=${operatorId}`;
        }
        return this.request('GET', endpoint);
    }
    
    // ==================== Dashboard ====================
    
    async getDashboardStats() {
        return this.request('GET', '/dashboard/stats');
    }
    
    async getDashboardSummary() {
        return this.request('GET', '/dashboard/summary');
    }
}

// Global API instance
const api = new LabDataAPI();
