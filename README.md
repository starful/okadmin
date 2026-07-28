# OK Admin — Work Hub

Local operations hub for the OK Series site fleet: site registry, content pipelines, Git/GitHub shipping, GSC/GA4 embeds, GCS images, and deploy orchestration.

**Local URL:** [http://127.0.0.1:8090](http://127.0.0.1:8090) (port **8090** avoids clashes with site apps on 8080)

## What it does

| Area | Description |
|------|-------------|
| **Dashboard** | All Hub sites from `sites.yaml` — Git summary, deploy status, links |
| **Per-site workflow** | ① Content ② SEO ③ Git ④ Deploy ⑤ Metrics ⑥ Images |
| **Ship · GitHub** | `Ship prep` (Claude ×1 → issue → branch → commit → push → PR), `Review & merge` (diff + checklist → squash merge) |
| **Content pipeline** | AI generation, image fetch, `build_data` per site (`pipeline_site_registry.py`) |
| **GSC / Analytics** | Embedded Search Console and GA4 views |
| **GCS images** | Per-site bucket prefix, Places search, Imagen prompts |
| **Calendar** | Firestore-backed ops events (FullCalendar) |

## Quick start

```bash
cd /opt/work/okadmin
chmod +x start.sh scripts/fetch_secrets.sh
./start.sh    # pulls secrets from GCP on first run if .env missing
```

Restart: `./restart.sh`

### macOS app bundle (optional)

```bash
/opt/homebrew/bin/python3 -m pip install pywebview pyobjc-framework-WebKit pyobjc-framework-Cocoa
./scripts/build-macos-app.sh --install
```

| App | Purpose |
|-----|---------|
| **OK Admin.app** | Native window |
| **OK Admin Dev.app** | Opens in browser |
| **OK Admin Stop.app** | Stops server |

Details: [mac/README.md](mac/README.md)

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORK_ROOT` | `/opt/work` | Monorepo root with site repos |
| `SITES_YAML` | `/opt/work/sites.yaml` | Site registry |
| `PORT` | `8090` | Hub HTTP port |
| `LOCAL_DEV_AUTH` | `1` | Skip Google OAuth locally |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Firestore, GA4 (optional) |
| `GSC_TOKEN_PATH` | — | Search Console OAuth (optional) |

Copy `okadmin/.env.example` → `.env`. Secrets: `./scripts/fetch_secrets.sh`.

### Local OAuth

If using Google login (`LOCAL_DEV_AUTH=0`), add redirect URIs in GCP:

- `http://127.0.0.1:8090/oauth/callback`
- `http://localhost:8090/oauth/callback`

### GitHub CLI (Ship workflow)

```bash
brew install gh
gh auth login
gh auth status
```

Ship uses local `gh` for issues, PRs, and squash merge. See [docs/GITHUB.md](docs/GITHUB.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Ship workflow (per site repo)

1. Edit content in `/opt/work/<site>`.
2. Open site in Hub → **③ Git** → **Ship prep** (optional hint; one Claude call drafts issue, commit message, PR).
3. Progress panel: draft → issue → branch → commit → push → PR.
4. **Review & merge** — read PR diff, complete checklist, **Approve & Squash merge**.
5. `git checkout main && git pull` in site repo → **④ Deploy**.

Manual steps (Issue / Branch / …) are under **Manual steps ▸**.

## Project layout

```text
okadmin/
├── app_factory.py          # Flask app
├── blueprints/             # Hub API, analytics, GSC, images, Instagram, …
├── github_ops.py           # gh CLI: issue, PR, review, ship_prepare
├── git_ops.py              # commit, push, branch, deploy jobs
├── pipeline_site_registry.py
├── static/site_hub.js      # Per-site workflow UI
├── templates/              # dashboard, site hub, embeds
├── sites.yaml              # (usually /opt/work/sites.yaml)
└── tests/
```

## Tests

```bash
cd /opt/work/okadmin
pytest tests/
```

## Cloud Run note

When deployed without `WORK_ROOT`, Git ops, content pipeline, and oktemplate clone are disabled in the UI (read-only hub features still work if configured).

Further reading: [docs/PHASE2.md](docs/PHASE2.md), [docs/GITHUB.md](docs/GITHUB.md).
