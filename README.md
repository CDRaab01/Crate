# Crate

Photo-to-shipped-package automation for eBay selling. Snap a picture, review an
AI-generated listing with two price points, approve, and Crate handles posting, sale
tracking, and shipping logistics.

Part of the personal app suite (Spotter · Plate · Cookbook · Dragonfly · Magpie ·
Remnant). Kotlin/Compose Android client over a FastAPI + Postgres backend; PULSE design
language via the shared `pulse-ui` library (copper-led); "Sign in with Dragonfly" SSO
only; deployed tailnet-only.

- **Build spec / source of truth:** [CLAUDE.md](CLAUDE.md)
- **As-built architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)

## Layout

```
android/   Kotlin + Jetpack Compose client (composite-builds ../Pulse)
server/    FastAPI + SQLAlchemy async + Alembic (Postgres)
deploy/    self-hosted runner redeploy script (Windows/Docker Desktop host)
```

## Run the server locally

```bash
cd server
cp .env.example .env    # set SECRET_KEY; DATABASE_URL points at 127.0.0.1:5438
docker compose up -d db # or point DATABASE_URL at any Postgres 16
./run.sh
```

## Tests

```bash
cd server && .venv/bin/python -m pytest   # needs a throwaway Postgres; see CLAUDE.md §8
cd android && ./gradlew :app:testDebugUnitTest
```
