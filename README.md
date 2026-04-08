# Network Template GitOps

A GitOps pipeline for managing Cisco Catalyst Center configuration templates. Templates are authored and tested in a **Stage** project, committed to Git as the single source of truth, validated by CI, and promoted to a **Prod** project after approval.

---

## Why GitOps for Network Templates?

Manual template management across environments is error-prone and hard to audit. This project brings software-delivery best practices to network infrastructure:

- **Single source of truth** -- Git holds every template version. No undocumented changes.
- **Peer review** -- Pull requests enforce code review before anything reaches production.
- **Automated validation** -- CI checks template existence, file format, and drift before promotion.
- **Approval gate** -- A senior engineer must approve before templates land in Prod.
- **Auditability** -- Every change is a Git commit with author, timestamp, and diff.
- **Rollback** -- Revert a Git commit to roll back a template change.

---

## Workflow

```
Engineer edits template in Stage project (Catalyst Center)
         |
         v
  Tests template on a test site / device
         |
         v
  Exports template and commits to Git (creates a Pull Request)
         |
         v
  CI Pipeline (Jenkins) -- triggered manually or via webhook:
    1. Resolve Branch & Commit  -- identify the template library commit
    2. Build Docker image       -- containerized execution environment
    3. Validate Stage           -- template exists in Stage project
    4. Drift Check              -- Git content == Stage content
         |
         v
  Approval Gate (Senior Engineer clicks "Proceed" in Jenkins console)
         |
         v
    5. Re-validate Drift  -- ensure Stage has not changed since approval
    6. Promote             -- import template from Stage into Prod project
```

### Environment Layout

A **single Catalyst Center instance** hosts two projects per template family:

| Catalyst Center Project | Purpose |
|---|---|
| `<folder>-stage` | Engineers author and test templates here |
| `<folder>-prod`  | Production templates promoted via the pipeline |

The Git repository that acts as the source of truth:
**https://github.com/prajravi/catalyst-template-library**

Repository structure inside that repo:

```
catalyst-template-library/
  network-templates/
    my_template.j2
    another_template.j2
```

Each top-level folder maps to a Catalyst Center project pair via the suffixes configured in `settings.yaml`.

---

## Project Structure

```
network-template-gitops/
  app/
    __init__.py
    __main__.py          # Entry point, logging config, pipeline stage logic
    error_handler.py     # Custom exception classes
    utils.py             # Catalyst Center SDK, GitHub API, and general helpers
  Dockerfile             # Production image (Python 3.10-slim)
  Jenkinsfile            # CI/CD pipeline definition (Docker-based)
  requirements.txt       # Python dependencies
  settings.yaml          # Project name suffixes and template folders
  .env.example           # Template for local credentials
  .gitignore
  README.md
```

---

## Local Setup

### Prerequisites

- Python 3.10+
- Docker Desktop (for containerized runs and Jenkins)
- Jenkins (installed locally or via Docker)
- A GitHub personal access token with `repo` read access
- Network access to your Catalyst Center instance

### 1. Clone and configure

```bash
git clone https://github.com/prajravi/network-template-gitops.git
cd network-template-gitops

# Create your local credentials file
cp .env.example .env
# Edit .env and fill in your Catalyst Center and GitHub credentials
```

Contents of `.env`:

```
CATC_BASE_URL=https://your-catalyst-center.example.com
CATC_USERNAME=admin
CATC_PASSWORD=your_password
CATC_VERIFY_SSL=true
GITHUB_TOKEN=ghp_your_token_here
```

### 2. Set up a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Find the commit SHA from the template library

The `--commit` argument expects a commit SHA from the **template library repo**
(not this pipeline repo). Use one of these methods:

**Option A -- Latest commit on a branch (recommended):**
```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/prajravi/catalyst-template-library/commits/main" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])"
```

**Option B -- From the GitHub UI:**
1. Go to https://github.com/prajravi/catalyst-template-library/commits/main
2. Click the commit you want to process.
3. Copy the full 40-character SHA from the URL or the page header.

**Option C -- Using git CLI (if you have the repo cloned):**
```bash
cd /path/to/catalyst-template-library
git log --oneline -5   # pick the SHA you want
```

### 4. Run the pipeline stages locally

```bash
# Set a variable for convenience
COMMIT_SHA=<paste-sha-from-step-3>

# Validate templates exist in Stage project
python -m app --commit $COMMIT_SHA --branch main --stage validate-stage

# Check for drift between Git and Stage
python -m app --commit $COMMIT_SHA --branch main --stage drift-check

# Validate Prod project exists
python -m app --commit $COMMIT_SHA --branch main --stage validate-prod

# Promote from Stage to Prod
python -m app --commit $COMMIT_SHA --branch main --stage promote
```

For feature branches (compares all changes against main -- no commit SHA needed):

```bash
python -m app --branch feature/update-acl --stage validate-stage
```

### 5. Run via Docker

```bash
docker build -t network-template-gitops .

docker run --rm --env-file .env network-template-gitops \
    --commit $COMMIT_SHA --branch main --stage promote
```

---

## Jenkins Setup

### Install Jenkins (macOS)

```bash
brew install jenkins-lts
brew services start jenkins-lts
```

Open http://localhost:8080 and complete the setup wizard. Install the
suggested plugins plus the **Pipeline** plugin.

### Create a Pipeline Job

1. **New Item** -> enter a name (e.g. `network-template-gitops`) -> **Pipeline** -> OK.
2. Under **Pipeline**, select **Pipeline script from SCM**.
3. Set SCM to **Git**, repository URL:
   ```
   https://github.com/prajravi/network-template-gitops.git
   ```
4. Branch Specifier: `*/main`
5. Script Path: `Jenkinsfile`
6. Click **Save**.

### Copy credentials to the Jenkins workspace

Jenkins needs a `.env` file in its workspace directory. Copy it once:

```bash
cp /path/to/your/.env ~/.jenkins/workspace/<job-name>/.env
```

> Replace `<job-name>` with the name you chose when creating the pipeline job
> (e.g. `network-template-gitops`). The `~/.jenkins/workspace/` path is the
> default on macOS; adjust if your Jenkins home is elsewhere.

### Pipeline Stages (Jenkinsfile)

The Jenkinsfile defines a Docker-based pipeline. Each stage runs inside a
freshly built container for isolation and reproducibility.

| # | Stage | What it does |
|---|---|---|
| 1 | **Resolve Branch & Commit** | Determines the Git branch and fetches the latest commit SHA from the template library repo (not the pipeline repo). |
| 2 | **Docker Build** | Builds the application Docker image. Verifies `.env` exists in the workspace. |
| 3 | **Validate Stage** | Runs the app with `--stage validate-stage`. Confirms every changed template exists in the Stage project on Catalyst Center. |
| 4 | **Drift Check** | Runs `--stage drift-check`. Compares Git file content against the Stage project -- they must match. |
| 5 | **Approval Gate** | Pauses the pipeline and waits for a human to click **Proceed** in the Jenkins console. Main branch only. |
| 6 | **Re-validate Drift** | Runs drift-check again after approval to ensure nothing changed while waiting. Main branch only. |
| 7 | **Promote to Prod** | Runs `--stage promote`. Exports each template from Stage and imports it into the Prod project. If a template was deleted in Git, it is removed from Prod (Stage copy is preserved). Main branch only. |

Stages 5-7 only execute on the `main` branch. Feature branches run stages 1-4
only, making them safe for pre-merge validation.

### Triggering the Pipeline

- **Manual:** Click **Build Now** in the Jenkins dashboard.
- **Webhook (production):** Configure a GitHub webhook pointing to
  `http://<jenkins-url>/github-webhook/` on push events to the template library
  repo.

---

## Configuration

### settings.yaml

```yaml
stage_suffix: "-stage"
prod_suffix: "-prod"
template_folders:
  - network-templates
```

- `stage_suffix` / `prod_suffix`: Appended to the Git folder name to derive Catalyst Center project names.
- `template_folders`: Folders where only `.j2` files are allowed (enforced by drift-check).

### Environment Variables (.env)

| Variable | Required | Description |
|---|---|---|
| `CATC_BASE_URL` | Yes | Catalyst Center URL (e.g. `https://10.10.20.85`) |
| `CATC_USERNAME` | Yes | Authentication username |
| `CATC_PASSWORD` | Yes | Authentication password |
| `CATC_VERIFY_SSL` | No | Set to `false` for self-signed certificates (default: `true`) |
| `GITHUB_TOKEN` | Yes | Personal access token with `repo` read access |
| `GITHUB_REPO_API` | No | Override the template library API URL |

---

## CLI Reference

```
python -m app [OPTIONS]

Options:
  --commit TEXT    Commit SHA from the template library repo (required for main branch)
  --branch TEXT    Branch name (default: main)
  --stage TEXT     Pipeline stage: validate-stage | validate-prod | drift-check | promote
```

---

## Architecture: Current Project vs Production

This project is set up for a **local development** environment. In a production deployment,
the architecture would differ:

| Aspect | Current Project | Production |
|---|---|---|
| Jenkins | Local macOS install | Centralized Jenkins server or cloud CI |
| Trigger | Manual "Build Now" | GitHub webhook on push/PR |
| Approval | Jenkins console click | PR review + branch protection rules |
| Docker | Docker Desktop | Containerized CI agents |
| Secrets | `.env` file in workspace | Jenkins credentials / Vault |
| Catalyst Center | Single instance (Stage + Prod projects) | Separate Stage and Prod instances possible |

---

## License

MIT
