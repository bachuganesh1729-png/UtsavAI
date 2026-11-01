# 🎊 UtsavAI — Your Celebration. Your Budget. Your Perfect Plan.

A professional, GenAI-powered celebration and event planning assistant built with **Python**, **Streamlit**, **Google Gemini API**, **SQLite** and **Plotly**.

---

## Features

| Module | Description |
|--------|-------------|
| 🎉 AI Event Planner | Generate personalised event plans with budget, timeline and vendor checklist |
| 💰 Budget Manager | Allocate, track and optimise your event budget with interactive charts |
| 📅 Timeline Generator | Preparation schedules with deadline tracking and task management |
| 🤝 Vendor Manager | Add, edit and track vendors by category and booking status |
| 💬 AI Assistant | Conversational planning help with event context awareness |

---

## Quick Start

### 1. Clone and set up

```bash
git clone https://github.com/your-repo/UtsavAI.git
cd UtsavAI
python -m venv .venv
.venv\Scripts\activate       # Windows
# or: source .venv/bin/activate  # macOS/Linux
python -m pip install -r requirements.txt
```

### 2. Configure your Gemini API key

```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

Edit `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your-api-key-here"
GEMINI_MODEL   = "gemini-2.5-flash-preview-05-20"
```

Get a free API key at [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

> **Note:** The app works without an API key. AI-powered features are disabled but all other tools (Budget Manager, Timeline, Vendor Manager) are fully functional.

### 3. Run

```bash
streamlit run app.py
```

---

## Configuration

| Setting | Source | Default |
|---------|--------|---------|
| `GEMINI_API_KEY` | `.streamlit/secrets.toml` or env var | *(none — AI disabled)* |
| `GEMINI_MODEL` | `.streamlit/secrets.toml` or env var | `gemini-2.5-flash-preview-05-20` |

The model name is fully configurable. See [supported models](https://ai.google.dev/gemini-api/docs/models).

---

## Running Tests

```bash
python -m pytest tests/ -v --tb=short
```

All tests run **without a Gemini API key** — the AI integration layer is fully mocked.

---

## Project Structure

```
UtsavAI/
├── app.py                          # Streamlit entry point
├── requirements.txt                # Pinned dependencies (Python ≥ 3.11)
├── .gitignore
├── README.md
├── .streamlit/
│   ├── config.toml                 # Theme configuration
│   └── secrets.toml.example        # Key template (copy → secrets.toml)
├── modules/                        # UI layer — Streamlit page modules
├── services/                       # Business logic & external integrations
│   ├── gemini_service.py           # Google Gemini API wrapper
│   ├── database_service.py         # SQLite CRUD operations
│   ├── budget_service.py           # Budget arithmetic (Python only)
│   ├── timeline_service.py         # Timeline generation & validation
│   └── vendor_service.py           # Vendor checklist logic
├── utils/                          # Pure helpers (no side effects)
│   ├── config.py                   # Secrets loading & app constants
│   ├── validators.py               # Input & AI response validation
│   ├── formatters.py               # Currency, date, text formatting
│   └── styles.py                   # CSS injection helpers
├── assets/
│   └── styles.css                  # Global premium CSS
└── tests/                          # pytest test suite
```

---

## Architecture

### Layer Contract

```
modules/  (UI only)
    ↓ calls
services/ (business logic + AI + DB)
    ↓ calls
utils/    (pure helpers — standard library only)
```

- `modules/` never imports `sqlite3` or `google.genai` directly.
- `services/` never imports `streamlit`.
- `utils/` never imports anything outside the standard library.

### AI Integration

- Uses `google-genai` SDK (`from google import genai`) — the official modern SDK.
- All AI responses are **schema-validated in Python** before use.
- **All budget arithmetic is computed in Python.** AI budget figures are suggestions only.
- Structured error results distinguish: `missing_credentials`, `rate_limit`, `timeout`, `invalid_response`, `api_error`, `unexpected`.

---

## ⚠️ Data Persistence — Streamlit Community Cloud

> **Important:** UtsavAI uses a local **SQLite database** (`utsavai.db`).
>
> On **Streamlit Community Cloud**, the filesystem is **ephemeral**. Your data **will be lost** when the app restarts or redeploys. This is a platform limitation, not a bug.
>
> - ✅ **Local use:** Data persists normally between sessions.
> - ❌ **Streamlit Cloud:** Data is lost on restart/redeploy.
>
> For persistent Cloud deployment, consider replacing SQLite with a managed database (e.g., Supabase, PlanetScale, or Neon).

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `streamlit` | 1.66.1 | UI framework |
| `google-genai` | 2.34.0 | Official Gemini SDK |
| `plotly` | 7.1.0 | Interactive charts |
| `pytest` | 9.2.0 | Unit testing |
| `pytest-mock` | 3.17.0 | Mocking in tests |

Requires **Python ≥ 3.11**.

---

## Security

- API keys are never hardcoded. Use `.streamlit/secrets.toml` (gitignored).
- All SQLite queries use parameterized placeholders — no string interpolation.
- AI-generated code is never executed.
- Logs never contain API keys or personal data.
- Column names in UPDATE queries are allowlisted — not taken from user input.

---

## Cultural Coverage

UtsavAI includes culturally informed suggestions for Indian celebrations including Telugu, Tamil, North Indian and other regional traditions. All cultural suggestions are framed as options, not universal requirements.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
