# Lab Data Upload System - Setup & Deployment Guide

A complete application for laboratory data management with testing time observation, manual data uploads, and role-based access control.

## Features

- **Role-Based Access Control**: Operator, Access Person, and Admin roles
- **Manual Data Upload**: Laboratory operators upload test data every 4 hours (configurable)
- **Testing Time Tracking**: Monitor active and completed testing sessions
- **Real-time Dashboard**: Access persons observe testing status and upload history
- **Upload Interval Configuration**: Admins can customize upload frequency
- **Supabase Integration**: Secure database with authentication and RLS policies

## Tech Stack

- **Backend**: Python with FastAPI
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **Database**: Supabase (PostgreSQL)
- **Authentication**: Supabase Auth with JWT tokens

## Project Structure

```
lab-data-upload/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── models.py            # Pydantic models
│   ├── config.py            # Configuration settings
│   ├── database.py          # Supabase database handler
│   ├── auth.py              # Authentication utilities
├── frontend/
│   ├── index.html           # Main HTML file
│   ├── css/
│   │   └── style.css        # Styling
│   └── js/
│       ├── api.js           # API client
│       └── app.js           # Application logic
├── requirements.txt         # Python dependencies
└── database_schema.sql      # Supabase schema setup
```

## Prerequisites

- Python 3.9 or higher
- Node.js/npm (optional, for frontend development)
- Supabase account (free tier available at https://supabase.com)
- Git (for version control)

## Setup Instructions

### 1. Create Supabase Project

1. Go to https://supabase.com and sign up/login
2. Create a new project:
   - Project Name: `lab-data-upload`
   - Database Password: (set a strong password)
   - Region: (choose closest to you)
3. Wait for the project to initialize (2-3 minutes)
4. Copy your project credentials:
   - Project URL (SUPABASE_URL)
   - Anon Key (SUPABASE_KEY)
   - Service Role Key (SUPABASE_SERVICE_KEY)

### 2. Set Up Database Schema

1. In Supabase dashboard, go to **SQL Editor**
2. Click **New Query**
3. Copy the entire content from `database_schema.sql`
4. Paste it into the SQL editor
5. Click **Run** to execute all SQL statements
6. Verify tables are created under **Table Editor**

### 3. Install Backend Dependencies

```bash
cd lab-data-upload
python -m venv venv

# On Linux/macOS
source venv/bin/activate

# On Windows
venv\Scripts\activate

pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the `backend` directory:

```env
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key

# Application Configuration
DEBUG=True
SECRET_KEY=your-secret-key-change-in-production

# Default upload interval in minutes (4 hours = 240 minutes)
DEFAULT_UPLOAD_INTERVAL=240
```

### 5. Start the Backend Server

```bash
cd backend
python main.py
```

The API will be available at `http://localhost:8000`

API Documentation (Swagger UI): `http://localhost:8000/docs`

### 6. Serve the Frontend

Option A: Using Python's built-in server
```bash
cd frontend
python -m http.server 8001
```

Option B: Using Node.js http-server
```bash
cd frontend
npx http-server
```

Option C: Using Live Server extension in VS Code
- Install "Live Server" extension
- Right-click on `index.html`
- Select "Open with Live Server"

Access the application at `http://localhost:8000/` or `http://localhost:8001/` depending on your choice.

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `GET /api/auth/verify` - Verify current token

### Data Uploads
- `POST /api/uploads/data` - Upload test data (operator)
- `GET /api/uploads/my-uploads` - Get operator's uploads
- `GET /api/uploads/all` - Get all uploads (access person)

### Upload Interval Configuration
- `GET /api/config/upload-interval` - Get current interval
- `POST /api/config/upload-interval` - Set interval (admin only)

### Testing Time Management
- `POST /api/testing/start` - Start new testing session (operator)
- `POST /api/testing/end/{session_id}` - End testing session (operator)
- `GET /api/testing/active` - Get active tests (access person)
- `GET /api/testing/history` - Get testing history (access person)

### Dashboard
- `GET /api/dashboard/stats` - Get dashboard statistics (access person)
- `GET /api/dashboard/summary` - Get user-specific summary

## User Roles

### Operator
- Upload test data
- View their own uploads
- Start/end testing sessions
- View their testing history
- See next upload deadline

### Access Person
- View all uploads with timestamps
- Monitor active testing sessions
- View testing history
- Monitor upload scheduling
- See dashboard statistics

### Admin
- All access person permissions
- Configure upload interval
- Manage user roles (via Supabase dashboard)

## Usage Guide

### For Laboratory Operators

1. **Login** with operator credentials
2. **Dashboard**: Shows number of uploads and next upload deadline
3. **Upload Data**:
   - Go to "Upload Data" section
   - Enter test name (required)
   - Add description (optional)
   - Paste test data in JSON format
   - Click "Upload Data"
4. **Testing Time**:
   - Start test by entering test name
   - System tracks start time automatically
   - End test when complete
   - Duration is calculated automatically

### For Access Persons

1. **Login** with access person credentials
2. **Dashboard**: View key statistics:
   - Total number of uploads
   - Number of active tests
   - Completed tests count
   - Number of operators
   - Last upload time
   - Next scheduled upload time
3. **Upload History**:
   - View all uploads in a table
   - Search by test name
   - Filter by date range
   - Click "View" to see upload details
4. **Testing Sessions**:
   - View all active testing sessions
   - See operator names and duration
   - Monitor testing progress

### For Admins

1. Access all access person features
2. **Settings**:
   - Go to "Settings" section
   - Adjust upload interval (minimum 1 minute, maximum 24 hours)
   - See interval preview before updating
   - Changes apply immediately

## Configuration Options

Edit `.env` file in the `backend` directory:

```env
# Default upload interval in minutes
DEFAULT_UPLOAD_INTERVAL=240  # 4 hours (change to 360 for 6 hours, 180 for 3 hours, etc.)

# Application mode
DEBUG=False  # Set to False in production

# CORS settings (for frontend access)
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
```

## Deployment to Production

### Using Heroku

1. Create `Procfile` in project root:
```
web: cd backend && python -m uvicorn main:app --host 0.0.0.0 --port $PORT
```

2. Deploy:
```bash
heroku login
heroku create your-app-name
heroku config:set SUPABASE_URL=your-url
heroku config:set SUPABASE_KEY=your-key
heroku config:set SUPABASE_SERVICE_KEY=your-service-key
heroku config:set SECRET_KEY=your-production-secret-key
heroku config:set DEBUG=False
git push heroku main
```

### Using Docker

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

WORKDIR /app/backend

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Troubleshooting

### Login Issues
- Check SUPABASE_URL and SUPABASE_KEY in `.env`
- Verify user exists in Supabase Auth
- Check browser console for error messages

### Upload Errors
- Verify JSON format in data field
- Ensure operator is logged in
- Check network connection

### Database Connection Issues
- Verify Supabase project is active
- Check SUPABASE_SERVICE_KEY is correct
- Ensure RLS policies are enabled

### Frontend Not Loading
- Check frontend server is running
- Verify backend API is running on port 8000
- Check browser console for CORS errors
- Update ALLOWED_ORIGINS in config.py if needed

## Security Considerations

1. **Change Default Secret Key**: Update SECRET_KEY in production
2. **Enable HTTPS**: Use SSL/TLS in production
3. **Strong Passwords**: Enforce strong password requirements
4. **RLS Policies**: Verify Row Level Security policies are active in Supabase
5. **API Rate Limiting**: Consider adding rate limiting middleware
6. **Regular Backups**: Enable automatic backups in Supabase

## Support & Documentation

- **Supabase Docs**: https://supabase.com/docs
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **Pydantic Docs**: https://docs.pydantic.dev
- **API Documentation**: Available at `/docs` endpoint when backend is running

## License

This project is open source and available under the MIT License.

---

**Created**: June 2026
**Version**: 1.0.0
