# Professional Algorithmic Trading Platform

A modular, scalable, and secure platform for assisted and automatic trading across Crypto and Traditional assets.

## 📁 Project Structure

```text
.
├── apps/
│   ├── api/                # FastAPI Gateway (Dashboard & Controller)
│   ├── engine/             # Core Trading Engine & Strategy execution
│   ├── bot_manager/        # Logic to manage bot lifecycles
│   ├── ai_engine/          # Local AI/LLM analysis & reporting
│   └── shared/             # Shared Pydantic models, Utils, DB models
├── docs/                   # Full Technical & Functional Documentation
├── scripts/                # Setup & Migration scripts
├── docker-compose.yml      # Orchestration of DB, Cache, and Apps
├── requirements.txt        # Python dependencies
└── README.md               # You are here
```

## 🚀 Getting Started

1. **Prerequisites**:
   - Docker & Docker Compose
   - Python 3.11+
   - [Optional] Ollama for local AI

2. **Setup**:
   ```bash
   pip install -r requirements.txt
   docker-compose up -d
   ```

3. **Documentation**:
   Refer to the `docs/` folder for:
   - [Architecture](docs/architecture.md)
   - [Functional Specs](docs/functional.md)
   - [Database Schema](docs/database_schema.md)
   - [API Specs](docs/api_spec.md)
   - [Roadmap](docs/roadmap.md)
