# Lab Data Upload System

A comprehensive web application for laboratory data management that enables laboratory operators to upload test data at regular intervals while allowing access persons to monitor testing progress and upload history in real-time.

## Overview

This system addresses the challenge of manual data uploads in laboratory environments where:
- Data cannot be uploaded automatically
- Operators must upload test data every 4 hours (configurable)
- Access persons need to observe testing time and data status
- Upload intervals need to be manually adjustable

## Key Features

✅ **Role-Based Access Control**
- Laboratory Operators: Upload data, track testing time
- Access Persons: Monitor uploads and testing sessions  
- Admins: Configure system settings

✅ **Manual Data Upload Management**
- 4-hour default upload interval (configurable from 1 minute to 24 hours)
- JSON-based test data upload
- Upload history with timestamps and metadata
- Operator tracking for each upload

✅ **Testing Time Observation**
- Start/end testing sessions
- Automatic duration calculation
- Active test monitoring
- Testing history with operator information

✅ **Real-Time Dashboard**
- Key statistics for access persons
- Active test count and duration
- Upload tracking with deadlines
- Operator activity monitoring

✅ **Local SQLite Database**
- Zero-config: the database file is created automatically on first run
- No external database or account required
- bcrypt-hashed passwords and JWT authentication

## Quick Start

### 1. Prerequisites
- Python 3.9+
- Modern web browser

### 2. Clone and Setup
```bash
cd lab-data-upload
cp .env.example backend/.env
# Optionally set a strong SECRET_KEY in backend/.env:
#   python -c "import secrets; print(secrets.token_urlsafe(64))"

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start Application
```bash
# Terminal 1 - Backend API (creates backend/local_database.db on first run)
cd backend
python main.py

# Terminal 2 - Frontend
cd frontend
python -m http.server 8001
```

Access the app at: http://localhost:8001

For detailed setup instructions, see [SETUP.md](SETUP.md)

## User Accounts

Register from the login screen to create a **Laboratory Operator** account
(self-registration always creates an operator).

To grant the elevated **access_person** or **admin** roles, update the local
database directly — for example:

```bash
cd backend
python -c "from database import db; import sqlite3; c=db.get_connection(); \
c.execute(\"UPDATE users SET role='admin' WHERE email=?\", ('you@lab.com',)); \
c.commit(); c.close(); print('done')"
```

## Architecture

### Backend (FastAPI)
- RESTful API with JWT authentication
- Local SQLite database (via the `sqlite3` standard library)
- Role-based access control
- Async/await support

### Frontend (Vanilla JavaScript)
- Responsive design (mobile-friendly)
- Real-time data updates
- Tab-based navigation
- Modal dialogs for details

### Database (SQLite)
- Users with role management
- Data uploads tracking
- Testing sessions monitoring
- Life tests, sync records, and system pause logs
- Tables are created automatically at startup (`init_db`)

## API Endpoints

```
Authentication:
  POST   /api/auth/register        - Register new user (always operator)
  POST   /api/auth/login           - Login
  GET    /api/auth/verify          - Verify token

Uploads:
  POST   /api/uploads/data         - Upload test data (operator)
  GET    /api/uploads/my-uploads   - Get my uploads (operator)
  GET    /api/uploads/all          - Get all uploads (access person)

Configuration:
  GET    /api/config/upload-interval        - Get interval
  POST   /api/config/upload-interval        - Set interval (admin)

Testing:
  POST   /api/testing/start                 - Start test (operator)
  POST   /api/testing/end/{id}              - End test (operator)
  GET    /api/testing/active                - Get active tests (access person)
  GET    /api/testing/history               - Get history (access person)

Dashboard:
  GET    /api/dashboard/stats               - Get stats (access person)
  GET    /api/dashboard/summary             - Get summary
```

## File Structure

```
lab-data-upload/
├── backend/
│   ├── main.py              # FastAPI application & routes
│   ├── models.py            # Pydantic data models
│   ├── config.py            # Configuration management
│   ├── database.py          # Local SQLite database handler
│   ├── security.py          # Password hashing (bcrypt)
│   ├── auth.py              # Authentication utilities (JWT)
│   ├── cycle_calculator.py  # ON-hours cycle analysis
│   └── local_database.db    # SQLite data file (auto-created, gitignored)
├── frontend/
│   ├── index.html           # Main application
│   ├── css/
│   │   └── style.css        # Styles & responsive design
│   └── js/
│       ├── api.js           # API client wrapper
│       └── app.js           # UI logic & handlers
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
├── SETUP.md                 # Detailed setup guide
└── README.md                # This file
```

## Configuration

Edit `backend/.env`:

```env
# Security
SECRET_KEY=your-secure-secret-key   # generate a strong random value
DEBUG=False                         # True only for local debugging

# Upload interval in minutes
DEFAULT_UPLOAD_INTERVAL=240  # 4 hours
```

The SQLite database lives at `backend/local_database.db` and needs no
configuration. Delete that file to reset all data.

## Customization

### Change Upload Interval
- Default: 4 hours (240 minutes)
- Edit `DEFAULT_UPLOAD_INTERVAL` in `.env`
- Or use Settings page (admin users)

### Customize Styling
- Edit `frontend/css/style.css`
- Update colors in `:root` CSS variables

### Add More Features
- Add routes in `backend/main.py`
- Update the schema in `backend/database.py` (`init_db`)
- Add UI sections in `frontend/index.html`

## Deployment

### Docker
```bash
docker compose up --build
```

### Heroku
1. Use the included `Procfile`
2. Set environment variables with `heroku config:set` (at minimum `SECRET_KEY`)
3. Deploy with `git push heroku main`

Note: SQLite is stored on the local filesystem. On ephemeral platforms
(Heroku dynos, Cloud Run) data does not persist across restarts — mount a
persistent volume or migrate to a managed database for production use.

## Security

- ✅ bcrypt-hashed passwords (legacy hashes upgraded on next login)
- ✅ JWT authentication (HS256) with a required secret key
- ✅ Self-registration restricted to the operator role
- ✅ CORS protection
- ✅ Environment variable secrets

**Important**: Set a strong `SECRET_KEY` and `DEBUG=False` in production.

## Troubleshooting

**Can't login?**
- Confirm the account was registered (self-registration creates operators)
- Check the browser console for errors
- Delete `backend/local_database.db` to start fresh (destroys all data)

**API not responding?**
- Ensure the backend is running: `python main.py`
- Check port 8000 is available

**Database errors?**
- The schema is created automatically; if the file is corrupt, delete
  `backend/local_database.db` and restart the backend

See [SETUP.md](SETUP.md) for more troubleshooting.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.9+, FastAPI |
| Frontend | HTML5, CSS3, JavaScript |
| Database | SQLite (standard library) |
| Auth | JWT (PyJWT), bcrypt |
| Deployment | Docker, Heroku |

## License

MIT License - Feel free to use and modify

## Support

- 📖 See [SETUP.md](SETUP.md) for detailed documentation
- 🚀 [FastAPI Documentation](https://fastapi.tiangolo.com)

---

**Version**: 1.0.0  
**Last Updated**: July 2026  
**Status**: Production Ready ✅
# Life-test-observation
