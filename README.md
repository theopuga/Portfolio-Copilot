# Portfolio Copilot

A stateful investment portfolio management application powered by Backboard.io, providing AI-driven portfolio analysis, recommendations, and management.

## Overview

Portfolio Copilot is a full-stack application that helps investors manage their portfolios through:
- **AI-powered profile extraction** from natural language onboarding
- **Portfolio analysis** with comprehensive metrics and sector diversification
- **Intelligent recommendations** for portfolio construction and rebalancing
- **Portfolio history tracking** and comparison tools
- **Automatic ticker lookup** and sector classification

## Architecture

### Backend
- **FastAPI** REST API server
- **Backboard.io SDK** for AI-powered profile extraction and explanations
- **SQLite** database for ticker and sector data
- **Pydantic** models for data validation

### Frontend
- **React** with TypeScript
- **Vite** for build tooling
- **React Router** for navigation
- **Tailwind CSS** for styling
- **Radix UI** components
- **Recharts** for data visualization

## Features

### Investor Profile Management
- Initialize profile from natural language onboarding text
- Update profile with incremental changes
- Store profiles in Backboard.io memory for persistence

### Portfolio Analysis
- Compute portfolio metrics (concentration, diversification, sector allocation)
- Automatic ticker lookup and sector classification
- Constraint violation detection
- Drift analysis

### Recommendations
- Construct new portfolios from scratch
- Rebalance existing portfolios
- AI-generated explanations for recommendations
- Target allocation based on risk profile

### Portfolio Management
- Save portfolio snapshots
- View portfolio history
- Compare current vs recommended portfolios

## Setup

### Prerequisites
- Python 3.13+
- Node.js 18+
- Backboard.io API key and project ID

### Backend Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp env.example .env
```

Edit `.env` and set:
- `BACKBOARD_API_KEY`: Your Backboard.io API key
- `BACKBOARD_PROJECT_ID`: Your Backboard.io project ID
- `BACKBOARD_BASE_URL`: Backboard.io API base URL (default: https://app.backboard.io/api)
- `CORS_ORIGINS`: Allowed CORS origins (use `*` for localhost)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `BUDGET_MODE`: Set to `true` to disable expensive AI calls (default: `false`)

4. Run the server:
```bash
# Development
uvicorn backend.main:app --reload

# Production
./start_production.sh
```

The API will be available at `http://localhost:8000`

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm run dev
```

4. Build for production:
```bash
npm run build
```

The frontend will be available at `http://localhost:5173` (or the port Vite assigns)

## API Endpoints

### Profile Management
- `POST /profile/init` - Initialize investor profile from onboarding text
- `POST /profile/update` - Update investor profile
- `GET /profile/{user_id}` - Get investor profile

### Portfolio Analysis
- `POST /portfolio/analyze` - Analyze portfolio and compute metrics
- `POST /portfolio/snapshot` - Save portfolio snapshot
- `GET /portfolio/history/{user_id}` - Get portfolio history
- `POST /portfolio/compare` - Compare two portfolios

### Recommendations
- `POST /recommend` - Get portfolio recommendation (construct or rebalance)

### Ticker Management
- `POST /ticker/lookup` - Look up a ticker and add to database
- `POST /ticker/sectors` - Get sectors for multiple tickers
- `POST /ticker/lookup/debug` - Debug endpoint for ticker lookup

### System
- `GET /` - API information and available endpoints
- `GET /health` - Health check endpoint

## Project Structure

```
backboard_project/
├── backend/              # FastAPI backend
│   ├── main.py          # FastAPI application and routes
│   ├── models.py        # Pydantic data models
│   ├── portfolio.py     # Portfolio computation logic
│   ├── sector_data.py   # Sector data management
│   ├── ticker_lookup.py # Ticker lookup and classification
│   ├── backboard_client.py # Backboard.io SDK client
│   └── logging_config.py # Logging configuration
├── frontend/            # React frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── components/  # React components
│   │   │   ├── api/         # API client
│   │   │   └── utils/       # Utility functions
│   │   └── styles/          # CSS styles
│   └── package.json
├── data/                # Data files
│   ├── sectors.json     # Sector definitions
│   └── sector_aliases.json # Sector aliases
├── cli/                 # CLI tools
├── docs/                # Documentation
├── requirements.txt     # Python dependencies
├── env.example         # Environment variables template
└── README.md           # This file
```

## Usage

### Initializing a Profile

Send a POST request to `/profile/init` with:
```json
{
  "user_id": "user123",
  "onboarding_text": "I'm a 35-year-old looking to invest for retirement in 30 years. I'm comfortable with moderate risk and want to focus on technology and healthcare sectors."
}
```

### Analyzing a Portfolio

Send a POST request to `/portfolio/analyze` with:
```json
{
  "user_id": "user123",
  "holdings": [
    {"ticker": "AAPL", "weight": 0.4},
    {"ticker": "MSFT", "weight": 0.3},
    {"ticker": "GOOGL", "weight": 0.2}
  ],
  "cash_weight": 0.1
}
```

### Getting Recommendations

Send a POST request to `/recommend` with:
```json
{
  "user_id": "user123",
  "holdings": [...],  // Optional: omit for new portfolio construction
  "cash_weight": 0.1
}
```

## Configuration

### Budget Mode

Set `BUDGET_MODE=true` in `.env` to disable expensive AI model calls. In budget mode:
- Profile extraction still uses AI (CHEAP model)
- Recommendation explanations use template-based responses instead of STRONG model

### CORS Configuration

For localhost development, `CORS_ORIGINS=*` is acceptable. For production, specify exact domains:
```
CORS_ORIGINS=https://app.example.com,https://www.example.com
```

### Logging

Logs are written to stdout by default. To write to a file, set `LOG_FILE` in `.env`:
```
LOG_FILE=/var/log/portfolio-copilot/app.log
```

## Development

### Running Tests

The project uses pytest for testing. Run tests with:
```bash
pytest
```

### Code Style

The backend follows PEP 8 Python style guidelines. The frontend uses ESLint and Prettier.


