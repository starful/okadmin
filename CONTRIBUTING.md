# Contributing

## Workflow (production only)

1. **Ship prep** (one Claude call): Issue → branch → commit → push → PR — or manual steps below.
2. **Review & merge** in okadmin — read diff, checklist, squash merge to `main`.
3. `git checkout main && git pull`, then **Deploy** from the okadmin **Deploy** tab.

Do not deploy from feature branches to production.

## Branches

| Prefix | Use |
|--------|-----|
| `feat/` | New feature |
| `fix/` | Bug fix |
| `chore/` | Tooling, deps, no user-facing change |

## Commits

- One logical change per PR when possible.
- Never commit `.env`, keys, or `secrets/`.

## GitHub CLI

Local Work Hub uses [`gh`](https://cli.github.com/) for issues and pull requests:

```bash
gh auth login
gh auth status
```

## Local checks

```bash
# okadmin
pytest tests/

# Site repo (after merge to main)
cd /opt/work/<site> && ./deploy.sh --deploy-only
```
