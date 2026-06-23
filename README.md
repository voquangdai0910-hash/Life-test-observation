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

✅ **Supabase Integration**
- Secure PostgreSQL database
- Built-in authentication
- Row-Level Security (RLS) policies
- Scalable and reliable infrastructure

## Quick Start

### 1. Prerequisites
- Python 3.9+
- Supabase account (free at https://supabase.com)
- Modern web browser

### 2. Clone and Setup
```bash
cd lab-data-upload
cp .env.example backend/.env
# Edit backend/.env with your Supabase credentials

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Setup Database
1. Go to Supabase SQL Editor
2. Copy contents of `database_schema.sql`
3. Run in SQL Editor
4. Verify tables are created

### 4. Start Application
```bash
# Terminal 1 - Backend API
cd backend
python main.py

# Terminal 2 - Frontend
cd frontend
python -m http.server 8001
```

Access the app at: http://localhost:8001

For detailed setup instructions, see [SETUP.md](SETUP.md)

## Demo Credentials

After setup, create test users:

**Laboratory Operator**
- Email: operator@lab.com
- Password: Test123!@
- Role: operator

**Access Person**
- Email: access@lab.com
- Password: Test123!@
- Role: access_person

**Admin**
- Email: admin@lab.com
- Password: Test123!@
- Role: admin

## Architecture

### Backend (FastAPI)
- RESTful API with JWT authentication
- Supabase database integration
- Role-based access control
- Async/await support

### Frontend (Vanilla JavaScript)
- Responsive design (mobile-friendly)
- Real-time data updates
- Tab-based navigation
- Modal dialogs for details

### Database (PostgreSQL via Supabase)
- Users with role management
- Data uploads tracking
- Testing sessions monitoring
- Upload interval configuration

## API Endpoints

```
Authentication:
  POST   /api/auth/register        - Register new user
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
│   ├── database.py          # Supabase database handler
│   ├── auth.py              # Authentication utilities
│   └── __pycache__/         # Python cache
├── frontend/
│   ├── index.html           # Main application
│   ├── css/
│   │   └── style.css        # Styles & responsive design
│   └── js/
│       ├── api.js           # API client wrapper
│       └── app.js           # UI logic & handlers
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
├── database_schema.sql      # Database setup
├── SETUP.md                 # Detailed setup guide
└── README.md                # This file
```

## Configuration

Edit `backend/.env`:

```env
# Supabase
SUPABASE_URL=your-url
SUPABASE_KEY=your-key
SUPABASE_SERVICE_KEY=your-service-key

# Upload interval in minutes
DEFAULT_UPLOAD_INTERVAL=240  # 4 hours

# Security
SECRET_KEY=your-secure-secret-key
DEBUG=False  # In production
```

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
- Update database schema in `database_schema.sql`
- Add UI sections in `frontend/index.html`

## Deployment

### Heroku
1. Create Procfile
2. Set environment variables with `heroku config:set`
3. Deploy with `git push heroku main`

### Docker
See `Dockerfile` example in [SETUP.md](SETUP.md)

### Cloud Platforms
- AWS App Runner / Lambda
- Google Cloud Run
- Azure App Service

## Security

- ✅ JWT authentication with Supabase
- ✅ Row-Level Security (RLS) policies
- ✅ HTTPS/SSL ready
- ✅ CORS protection
- ✅ Environment variable secrets

**Important**: Change `SECRET_KEY` in production!

## Troubleshooting

**Can't login?**
- Verify Supabase credentials in `.env`
- Check user exists in Supabase Auth
- Check browser console for errors

**API not responding?**
- Ensure backend is running: `python main.py`
- Check port 8000 is available
- Verify SUPABASE_URL is correct

**Database errors?**
- Run `database_schema.sql` in Supabase SQL Editor
- Verify RLS policies are enabled
- Check SUPABASE_SERVICE_KEY is correct

See [SETUP.md](SETUP.md) for more troubleshooting.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.9+, FastAPI |
| Frontend | HTML5, CSS3, JavaScript |
| Database | PostgreSQL (Supabase) |
| Auth | Supabase Auth, JWT |
| Deployment | Docker, Heroku, Cloud Run |

## License

MIT License - Feel free to use and modify

## Support

- 📖 See [SETUP.md](SETUP.md) for detailed documentation
- 🔗 [Supabase Documentation](https://supabase.com/docs)
- 🚀 [FastAPI Documentation](https://fastapi.tiangolo.com)

---

**Version**: 1.0.0  
**Last Updated**: June 2026  
**Status**: Production Ready ✅
# Life-test-observation
