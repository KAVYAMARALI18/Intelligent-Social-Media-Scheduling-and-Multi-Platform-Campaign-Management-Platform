# SocialPilot – Social Media Management Platform

SocialPilot is a full-stack social media management platform that helps users connect social accounts, create and manage posts, schedule content, organize campaigns, and monitor publishing activity from one dashboard.

The frontend is built with React and Vite, the backend uses FastAPI and SQLAlchemy, and PostgreSQL stores application data.

## 🚀 Features

- 🔐 User registration and secure login
- 👤 User and role-based access
- 📊 Dashboard with social media activity and statistics
- 🔗 Social media account integration
- 📝 Create and manage social media posts
- 📅 Schedule posts for future publishing
- 📢 Campaign creation and management
- 📤 Social media publishing
- 📋 Publishing queue
- 📈 Analytics and performance monitoring
- 🔔 Notifications
- ⚙️ User settings
- 🛡️ Admin dashboard and administration features
- 🌙 Light/Dark mode
- 📱 Responsive user interface
- 🤖 Integration with social-media APIs
- 🖼️ Image and video post support

## 🌐 Supported Platforms

SocialPilot is designed to integrate with multiple social media platforms, including:

- Facebook
- Instagram
- LinkedIn
- YouTube
- X (Twitter)

The available features depend on the APIs, permissions, and configurations provided by each platform.

## 🛠️ Tech Stack

### Frontend

- React.js
- JavaScript
- HTML5
- CSS3
- Vite
- React Context API

### Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- JWT Authentication
- REST APIs

### Database

- PostgreSQL

### Development Tools

- Git
- GitHub
- VS Code
- Postman

## ⚙️ Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/springboardmentor28126u/Intelligent-Social-Media-Scheduling-and-Multi-Platform-Campaign-Management-Platform.git
cd SocialPilot
git checkout Kavya-M-Arali
```

### 2. Backend Setup
If your frontend is served from more than one host, set `FRONTEND_URL` to
the primary origin and list any additional allowed origins in `FRONTEND_URLS`
as a comma-separated list. X and Facebook OAuth callbacks return the browser
to the same allowed frontend origin where the user started connecting.

## AI caption generator

The Create Post page can generate an editable social caption through the
authenticated `POST /ai/captions/generate` endpoint. Configure a Groq API key
in `backend/.env` before starting the backend:

```env
GROQ_API_KEY=your-groq-api-key
```

Optionally set `GROQ_MODEL` to use another model available to your Groq
account. The default is `qwen/qwen3.8-27b`. The endpoint requires the
existing JWT bearer token and accepts a topic, platform, and tone. It returns
an editable caption with relevant hashtags; it does not create, schedule, or
publish a post.

To test locally, start the backend from `backend` with
`uvicorn app.main:app --reload`, and start the frontend from `frontend` with
`npm run dev`. Sign in, open **Create Post**, describe the topic, select a
platform and tone, then choose **Generate Caption + Hashtags**. Edit the
result before copying it or using it in the existing post-content field.

## AI post rewriter

The Create Post content editor includes **AI Rewrite**. It uses the
authenticated `POST /ai/captions/rewrite` endpoint and the existing Groq
configuration (`GROQ_API_KEY` and optional `GROQ_MODEL`). Review the original
and rewritten text side by side; the post editor changes only when you choose
**Use Rewritten Content**. Rewriting never publishes or schedules a post.

## Analytics

The authenticated `GET /analytics/advanced` endpoint summarizes existing post
records by date, status, platform, and campaign. It accepts `start_date`,
`end_date`, `platform`, and `campaign_id` query parameters. Post activity is
aggregated in the database; date series use daily buckets for ranges up to one
year and monthly buckets for longer ranges. Engagement, reach, impressions,
and similar metrics are reported as unavailable until the connected platforms
provide actual metric data; the analytics UI does not estimate them.

Instagram is the only provider with post and follower metric synchronization
currently implemented. Published Instagram post metrics and follower counts
are captured once daily by the existing scheduler. Historical charts use those
recorded snapshots and therefore begin only after collection starts; the app
does not reconstruct earlier history. Engagement is the provider's recorded
engagement value (or likes plus comments when both values are present), and
engagement rate is calculated only when both engagement and a non-zero reach
value are available. Missing or unsupported provider metrics remain null.
Revenue and ROI remain unavailable until actual revenue data is recorded.

The Analytics page can export the active date, platform, and campaign filters
as CSV or Excel (`.xlsx`) using the authenticated `GET /analytics/export`
endpoint. Choose `post_details`, `platform_summary`, or `campaign_summary`
in the UI (the API uses the corresponding `report_type` query parameter) and
select `file_format=csv` or `file_format=xlsx`. The endpoint scopes every
export to the authenticated user's posts and their owned accounts and
campaigns. Platform engagement columns are marked `Data unavailable` until
real metrics are stored; export rows do not include post content, credentials,
or tokens.

Navigate to the backend:

```bash
cd backend
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file inside the `backend` directory.

Example:

```env
DATABASE_URL=your_postgresql_database_url
SECRET_KEY=your_secret_key

FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret
FACEBOOK_CONFIG_ID=your_facebook_config_id
FACEBOOK_REDIRECT_URI=your_facebook_redirect_uri

LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret
LINKEDIN_REDIRECT_URI=your_linkedin_redirect_uri

GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=your_google_redirect_uri

X_CLIENT_ID=your_x_client_id
X_CLIENT_SECRET=your_x_client_secret
X_REDIRECT_URI=your_x_redirect_uri
```

### 4. Database Migration

Run Alembic migrations:

```bash
alembic upgrade head
```

### 5. Start the Backend

```bash
uvicorn app.main:app --reload
```

The backend will run at:

```
http://127.0.0.1:8000
```

FastAPI documentation:

```
http://127.0.0.1:8000/docs
```

### 6. Start the Frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend will normally be available at:

```
http://localhost:5173
```

## 🔑 Authentication

SocialPilot uses JWT-based authentication.

The authentication flow includes:

- User registration
- User login
- Password verification
- JWT access token generation
- Protected API routes
- Role-based access for administrative features

## 📱 Social Media Integration

Users can connect their social media accounts through the **Social Accounts** section.

The general flow is:

```text
User
 ↓
Connect Social Account
 ↓
OAuth Authorization
 ↓
Access Token
 ↓
SocialPilot
 ↓
Save Connected Account
 ↓
Create / Schedule / Publish Posts
```

Each platform uses its respective OAuth/API requirements.

## 📝 Post Management

Users can:

- Create posts
- Add captions/content
- Upload supported media
- Select connected social accounts
- Publish posts
- Schedule posts
- View publishing status

## 📅 Campaign Management

Campaigns allow users to organize social media content around a particular marketing activity.

A campaign can contain:

- Campaign name
- Description
- Start/end dates
- Posts
- Publishing schedule
- Campaign status

## 📊 Dashboard & Analytics

The dashboard provides a centralized view of SocialPilot activity, including:

- Connected accounts
- Posts
- Campaigns
- Publishing activity
- Analytics
- Scheduled content

## 📋 Publishing Queue

The publishing queue helps manage scheduled posts and their publishing status.

Typical statuses include:

```text
Scheduled
   ↓
Processing
   ↓
Published
```

Failed publishing attempts can also be tracked for debugging and retry handling.

## 🛡️ Admin Features

The admin section provides administrative functionality such as:

- User management
- Dashboard statistics
- System-level information
- Administrative controls

Access to administrative features is restricted according to the user's role.

## 🎨 User Interface

The frontend includes:

- Responsive dashboard
- Sidebar navigation
- Workspace layout
- Forms
- Tables
- Cards
- Modals
- Notifications
- Light/Dark theme support
- Responsive design

## 🧪 Testing

Backend tests are maintained for important application functionality, including:

- Social media publishing
- OAuth state handling
- Backend API behavior

Run tests using:

```bash
pytest
```

## 🔒 Security

The project follows basic security practices including:

- JWT authentication
- Password hashing
- Protected API routes
- Role-based authorization
- Environment variables for credentials
- OAuth-based social account authentication
- CORS configuration

## Demo data

To populate the database with mock campaigns, social accounts, and scheduled posts for an existing user, run:

```bash
cd backend
./.venv/Scripts/python.exe seed_demo.py --email your-user@example.com
```

This creates sample Facebook, Instagram, and LinkedIn records plus a few campaign and post states so the dashboard, planner, and analytics views have realistic data to work with. The demo accounts are intentionally created without real tokens.
