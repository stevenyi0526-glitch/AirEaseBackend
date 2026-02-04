<p align="center">
  <img src="https://img.shields.io/badge/Platform-iOS%20%7C%20Web-blue?style=for-the-badge" alt="Platform"/>
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/AI-Google%20Gemini-4285F4?style=for-the-badge&logo=google" alt="Gemini AI"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">✈️ AirEase</h1>
<h3 align="center">Your Journey, Your Story</h3>

<p align="center">
  <strong>AI-Powered Flight Experience Optimizer</strong><br/>
  Find the perfect flight based on comfort, reliability, service quality, and value — not just price.
</p>

---

## 🌟 Overview

**AirEase** is a full-stack flight booking companion that revolutionizes how travelers find flights. Unlike traditional search engines that focus solely on price, AirEase provides a comprehensive **AirEase Score** that evaluates flights across multiple dimensions tailored to your travel persona.

Whether you're a **budget-conscious student**, a **time-sensitive business traveler**, or a **comfort-focused family**, AirEase personalizes recommendations to match your unique priorities.

---

## ✨ Key Features

### 🤖 AI-Powered Natural Language Search
Search for flights using natural language like:
- *"Fly to Tokyo next Friday morning, most comfortable"*
- *"Cheapest business class to Singapore"*
- *"Morning flight to Seoul next Monday"*

Powered by **Google Gemini AI** to understand and parse your travel intent.

### 📊 Smart Scoring System
Our proprietary **AirEase Score** evaluates each flight on:
| Dimension | Description |
|-----------|-------------|
| 🎯 **Reliability** | On-time performance based on airline OTP data |
| 🛋️ **Comfort** | Seat width, pitch, recline, and aircraft type |
| 👨‍✈️ **Service** | Airline service ratings from real user reviews |
| 💰 **Value** | Price competitiveness for the route |
| 🎬 **Amenities** | WiFi, power outlets, IFE, meals |
| ⏱️ **Efficiency** | Flight duration and direct flight bonus |

### 👤 Personalized Traveler Profiles
Different scoring weights for different travelers:
- **Student** → Prioritizes price and direct flights
- **Business** → Prioritizes reliability and service
- **Family** → Prioritizes comfort and amenities

### 🔍 Comprehensive Flight Details
- Real-time flight data via **SerpAPI Google Flights**
- Aircraft comfort specifications (seat width, pitch, IFE screens)
- Airline reliability metrics (on-time performance %)
- User review summaries from thousands of reviews
- Interactive route maps with layover visualization

### ⚖️ Side-by-Side Comparison
Compare up to 4 flights with:
- Visual radar charts for score dimensions
- Amenity comparison grid
- Best value highlighting
- PDF export for sharing

### ❤️ Favorites & Traveler Management
- Save favorite flights for later
- Manage traveler profiles with passport info
- Sync across devices when signed in

### 📝 Feedback & Error Reporting
- Report aircraft mismatches, price errors, or missing info
- Help improve data accuracy for the community

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLIENTS                              │
├─────────────────┬───────────────────────────────────────────┤
│   iOS App       │              Web App                       │
│   (SwiftUI)     │        (React + TypeScript)                │
│                 │          + Tailwind CSS                    │
└────────┬────────┴────────────────┬──────────────────────────┘
         │                         │
         │         REST API        │
         ▼                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI)                         │
├─────────────────────────────────────────────────────────────┤
│  Routes:                                                     │
│  • /v1/flights    - Flight search & details                  │
│  • /v1/ai         - Natural language parsing                 │
│  • /v1/auth       - User authentication (JWT)                │
│  • /v1/airports   - Airport search & nearby                  │
│  • /v1/recommendations - AI-powered suggestions              │
│  • /reports       - Feedback & error reporting               │
├─────────────────────────────────────────────────────────────┤
│  Services:                                                   │
│  • SerpAPI Service      - Real Google Flights data           │
│  • Gemini AI Service    - NLP query parsing                  │
│  • Scoring Service      - Multi-dimensional scoring          │
│  • Aircraft Comfort     - Seat specs from DB                 │
│  • Airline Reliability  - OTP data from DB                   │
│  • Airline Reviews      - Aggregated user reviews            │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATABASE (PostgreSQL)                     │
├─────────────────────────────────────────────────────────────┤
│  • users              - User accounts & preferences          │
│  • favorites          - Saved flights                        │
│  • travelers          - Traveler profiles                    │
│  • airports           - 70,000+ airports worldwide           │
│  • aircraft_comfort   - Seat specs for 50+ aircraft models   │
│  • airline_reliability- OTP data for 100+ airlines           │
│  • airline_reviews    - 100,000+ user reviews                │
│  • reports            - User feedback & corrections          │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

### Backend
| Technology | Purpose |
|------------|---------|
| **FastAPI** | High-performance Python web framework |
| **PostgreSQL** | Primary database |
| **SQLAlchemy** | ORM for database operations |
| **Google Gemini AI** | Natural language understanding |
| **SerpAPI** | Real-time Google Flights data |
| **JWT (python-jose)** | Authentication tokens |
| **Pydantic** | Data validation |

### Web Frontend
| Technology | Purpose |
|------------|---------|
| **React 19** | UI library |
| **TypeScript** | Type safety |
| **Vite** | Build tool |
| **Tailwind CSS** | Styling |
| **TanStack Query** | Data fetching & caching |
| **Zustand** | State management |
| **Recharts** | Price trend charts |
| **Leaflet** | Route maps |
| **jsPDF** | PDF export |

### iOS App
| Technology | Purpose |
|------------|---------|
| **SwiftUI** | Native UI framework |
| **Swift 5.9+** | Programming language |
| **Swift Charts** | Price trend visualization |
| **async/await** | Networking |
| **MVVM** | Architecture pattern |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL 14+
- Xcode 15+ (for iOS)

### 1. Clone the Repository
```bash
git clone https://github.com/stevenyi0526-glitch/AirEase.git
cd AirEase
```

### 2. Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or .\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your API keys:
# - GEMINI_API_KEY
# - SERPAPI_KEY
# - DATABASE_URL

# Run database migrations
psql -U your_user -d airease -f schema.sql

# Start the server
python run.py
```

The API will be available at `http://localhost:8000`
- Swagger Docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 3. Web Frontend Setup
```bash
cd AirEaseWeb

# Install dependencies
npm install

# Start development server
npm run dev
```

The web app will be available at `http://localhost:5173`

### 4. iOS App Setup
```bash
cd AirEase
open AirEase.xcodeproj
```

Configure your environment:
1. Create a `.env` file in the project root
2. Add your API keys
3. Build and run on simulator or device

---

## 📡 API Endpoints

### Flights
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/flights/search` | Search flights with filters |
| `GET` | `/v1/flights/{id}` | Get flight details |
| `GET` | `/v1/flights/{id}/price-history` | Get price trends |

### AI
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/ai/search` | Parse natural language query |
| `POST` | `/v1/ai/explain` | Generate score explanation |

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/auth/register` | Create new account |
| `POST` | `/v1/auth/login` | Sign in |
| `GET` | `/v1/auth/me` | Get current user |

### Airports
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/airports/search` | Search airports by name/code |
| `GET` | `/v1/airports/nearest` | Find nearest airport |
| `GET` | `/v1/airports/route/{from}/{to}` | Get route with layovers |

### Recommendations
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/recommendations/preferences` | Get user preferences |
| `POST` | `/v1/recommendations/generate` | Generate AI recommendations |

---

## 📸 Screenshots

<p align="center">
  <i>Coming soon - Beautiful UI screenshots showcasing the app experience</i>
</p>

---

## 🗂️ Project Structure

```
AirEase/
├── AirEase/                    # iOS App (SwiftUI)
│   ├── AirEase/
│   │   ├── App/                # App configuration
│   │   ├── Core/               # Models, Services, Utilities
│   │   └── Features/           # UI Features (Search, FlightList, Detail, etc.)
│   └── AirEase.xcodeproj
│
├── AirEaseWeb/                 # Web App (React + TypeScript)
│   ├── src/
│   │   ├── api/                # API client functions
│   │   ├── components/         # Reusable UI components
│   │   ├── pages/              # Page components
│   │   ├── stores/             # Zustand state stores
│   │   └── utils/              # Utility functions
│   └── package.json
│
├── backend/                    # Backend API (FastAPI)
│   ├── app/
│   │   ├── routes/             # API endpoints
│   │   ├── services/           # Business logic
│   │   ├── models.py           # Pydantic models
│   │   └── database.py         # DB connection
│   ├── migrations/             # SQL migrations
│   └── requirements.txt
│
└── README.md                   # This file
```

---

## 🔐 Environment Variables

### Backend (.env)
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/airease

# AI Services
GEMINI_API_KEY=your_gemini_api_key
SERPAPI_KEY=your_serpapi_key

# Authentication
JWT_SECRET_KEY=your_jwt_secret
JWT_ALGORITHM=HS256

# Email (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email
SMTP_PASSWORD=your_app_password
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **SerpAPI** for providing real-time Google Flights data
- **Google Gemini** for powering our AI features
- **OurAirports** for comprehensive airport data
- **Airline Quality** for user review data

---

<p align="center">
  Made with ❤️ by the AirEase Team
</p>

<p align="center">
  <a href="https://github.com/stevenyi0526-glitch/AirEase">⭐ Star us on GitHub</a>
</p>
