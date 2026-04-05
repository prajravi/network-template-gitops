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
  CI Pipeline (Jenkins):
    1. Build Docker image
    2. Validate Stage  -- template exists in Stage project
    3. Drift Check     -- Git content == Stage content
         |
         v
  Approval Gate (Senior Engineer reviews the PR in Jenkins)
         |
         v
    4. Re-validate drift -- ensure Stage has not changed since approval
    5. Promote           -- import template from Stage project into Prod project
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
  Dockerfile             # Production image
  Jenkinsfile            # CI/CD pipeline definition
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
- Docker (for containerized runs and Jenkins)
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

### 3. Run the pipeline stages manually

```bash
# Validate templates exist in Stage project
python -m app --commit <sha> --branch main --stage validate-stage

# Check for drift between Git and Stage
python -m app --commit <sha> --branch main --stage drift-check

# Validate Prod project exists
python -m app --commit <sha> --branch main --stage validate-prod

# Promote from Stage to Prod
python -m app --commit <sha> --branch main --stage promote
```

For feature branches (compares all changes against main):

```bash
python -m app --branch feature/update-acl --stage validate-stage
```

### 4. Run via Docker

```bash
docker build -t network-template-gitops .
docker run --rm --env-file .env network-template-gitops \
    --commit <sha> --branch main --stage promote
```

---

## Jenkins Setup (Local)

### Option A: Jenkins via Docker

```bash
docker run -d \
  --name jenkins \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkins/jenkins:lts
```

Retrieve the initial admin password:

```bash
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Install the suggested plugins plus the **Pipeline** and **Docker Pipeline** plugins.

### Option B: Jenkins installed natively

Follow the official Jenkins installation guide for macOS. Ensure Docker is available on the Jenkins agent.

### Create a Pipeline Job

1. New Item -> Pipeline.
2. Under Pipeline, select "Pipeline script from SCM".
3. Set SCM to Git, repository URL to your network-template-gitops repo.
4. Script Path: `Jenkinsfile`.
5. Under Build Triggers, configure a webhook or poll SCM as needed.
6. Place a `.env` file in the Jenkins workspace (or inject environment variables via Jenkins credentials).

The Jenkinsfile defines these stages:
1. **Docker Build** -- builds the application image.
2. **Validate Stage** -- ensures templates exist in the Stage project.
3. **Drift Check** -- verifies Git content matches Stage.
4. **Approval Gate** -- manual approval (main branch only).
5. **Re-validate Drift** -- confirms nothing changed after approval.
6. **Promote to Prod** -- imports templates from Stage into Prod.

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

---

## CLI Reference

```
python -m app [OPTIONS]

Options:
  --commit TEXT    Commit SHA to process (required for main branch)
  --branch TEXT    Branch name (default: main)
  --stage TEXT     Pipeline stage: validate-stage | validate-prod | drift-check | promote
```

---

## License

MIT
