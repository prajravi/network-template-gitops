"""
Utility module for Network Template GitOps.

Provides:
  - General helpers (hashing, content normalization, ID stripping)
  - Catalyst Center SDK integration (authentication, project and template operations)
  - GitHub API integration (commit data, file retrieval, branch comparison)
"""

import os
import time
import hashlib
import base64
import logging

import requests
from dnacentersdk import api

from app.error_handler import (
    AuthenticationError,
    CatalystAPIError,
    ProjectMissingError,
    GitHubAPIError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def create_timestamp_label():
    """
    Generate a timestamp string in the format 'YYYYMMDD_HHMM'.

    :return: Formatted timestamp string.
    """
    t = time.localtime()
    hour = f"0{t.tm_hour}" if t.tm_hour < 10 else f"{t.tm_hour}"
    minute = f"0{t.tm_min}" if t.tm_min < 10 else f"{t.tm_min}"
    month = f"0{t.tm_mon}" if t.tm_mon < 10 else f"{t.tm_mon}"
    day = f"0{t.tm_mday}" if t.tm_mday < 10 else f"{t.tm_mday}"
    return f"{t.tm_year}{month}{day}_{hour}{minute}"


def strip_template_ids(obj):
    """
    Recursively remove 'id' and 'templateId' keys from a dictionary or list.
    Required before importing a template into a different project because
    IDs are instance-specific and would cause conflicts.

    :param obj: Input dictionary or list.
    :return: Cleaned copy with 'id' and 'templateId' keys removed.
    """
    if isinstance(obj, dict):
        return {
            k: strip_template_ids(v)
            for k, v in obj.items()
            if k not in ("id", "templateId")
        }
    elif isinstance(obj, list):
        return [strip_template_ids(item) for item in obj]
    return obj


def normalize_content(content):
    """
    Normalize template content by stripping per-line whitespace,
    removing blank lines, and standardizing line endings.

    :param content: Raw template content string.
    :return: Normalized content string.
    """
    lines = [line.strip() for line in content.splitlines()]
    return "\n".join(line for line in lines if line)


def sha256_hash(content):
    """
    Compute a SHA-256 hash of the given content after normalization.

    :param content: Template content string.
    :return: Hex digest of the normalized content.
    """
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def content_is_equal(content_a, content_b):
    """
    Compare two template content strings after normalization.

    :param content_a: First template content string.
    :param content_b: Second template content string.
    :return: True if normalized contents match, False otherwise.
    """
    return sha256_hash(content_a) == sha256_hash(content_b)


# ---------------------------------------------------------------------------
# Catalyst Center SDK functions
# ---------------------------------------------------------------------------

def create_catc_session(username, password, base_url, verify=True):
    """
    Create and return an authenticated Catalyst Center SDK client.

    :param username: Catalyst Center username.
    :param password: Catalyst Center password.
    :param base_url: Base URL (e.g. https://catc.example.com).
    :param verify: Whether to verify SSL certificates.
    :return: Authenticated DNACenterAPI instance.
    :raises AuthenticationError: If credentials are missing or auth fails.
    """
    if not username or not password:
        msg = (
            f"Username and password must be provided for "
            f"Catalyst Center at {base_url}."
        )
        logger.error(msg)
        raise AuthenticationError(msg)
    try:
        cc = api.DNACenterAPI(
            username=username,
            password=password,
            base_url=base_url,
            version="2.3.7.6",
            verify=verify,
        )
        logger.info(f"Catalyst Center authentication successful for {base_url}")
        return cc
    except Exception as e:
        logger.exception(f"Catalyst Center authentication failed for {base_url}.")
        raise AuthenticationError(
            f"Catalyst Center authentication failed for {base_url}.", e
        ) from e


def init_catc_connection():
    """
    Initialize a Catalyst Center client using environment variables.

    Environment variables:
        CATC_BASE_URL   - Base URL of the Catalyst Center instance.
        CATC_USERNAME   - Username for authentication.
        CATC_PASSWORD   - Password for authentication.
        CATC_VERIFY_SSL - Optional. Set to 'false' to skip SSL verification.

    :return: Authenticated DNACenterAPI instance.
    :raises AuthenticationError: If required variables are missing or auth fails.
    """
    base_url = os.getenv("CATC_BASE_URL")
    username = os.getenv("CATC_USERNAME")
    password = os.getenv("CATC_PASSWORD")
    verify = os.getenv("CATC_VERIFY_SSL", "true").lower() != "false"

    if not base_url:
        raise AuthenticationError("CATC_BASE_URL environment variable is not set.")

    return create_catc_session(username, password, base_url, verify=verify)


def fetch_project_by_name(cc, project_name):
    """
    Look up a project by name on Catalyst Center.

    :param cc: DNACenterAPI instance.
    :param project_name: Exact project name to search for.
    :return: Project dictionary if found, None otherwise.
    :raises CatalystAPIError: If the API call fails.
    """
    try:
        projects = cc.configuration_templates.get_projects(project_name)
        for proj in projects:
            if proj["name"].strip() == project_name.strip():
                logger.info(f"Project '{project_name}' found.")
                return proj
        logger.warning(f"Project '{project_name}' not found.")
        return None
    except Exception as e:
        logger.exception(f"Failed to retrieve project '{project_name}'.")
        raise CatalystAPIError(
            f"Failed to retrieve project '{project_name}'.", e
        ) from e


def list_templates_in_project(project):
    """
    Return the list of templates contained in a project dictionary.

    :param project: Project dictionary (as returned by fetch_project_by_name).
    :return: List of template dictionaries, or empty list.
    """
    templates = project.get("templates", [])
    if not templates:
        logger.info("No templates found in the project.")
        return []
    logger.info(f"Found {len(templates)} templates in the project.")
    return templates


def export_template_from_project(cc, project_name, tmpl_name):
    """
    Export (pull) a template's full details from a Catalyst Center project.

    :param cc: DNACenterAPI instance.
    :param project_name: Name of the project containing the template.
    :param tmpl_name: Name of the template to export.
    :return: Template details dictionary.
    :raises ProjectMissingError: If the project does not exist.
    :raises CatalystAPIError: If the template is not found or the call fails.
    """
    try:
        project = fetch_project_by_name(cc, project_name)
        if project is None:
            raise ProjectMissingError(project_name)
        for tmpl in list_templates_in_project(project):
            if tmpl["name"] == tmpl_name:
                logger.info(
                    f"Template '{tmpl_name}' found in project '{project_name}'."
                )
                return cc.configuration_templates.get_template_details(
                    template_id=tmpl["id"]
                )
        raise CatalystAPIError(
            f"Template '{tmpl_name}' not found in project '{project_name}'."
        )
    except (ProjectMissingError, CatalystAPIError):
        raise
    except Exception as e:
        logger.exception(
            f"Failed to export template '{tmpl_name}' from project '{project_name}'."
        )
        raise CatalystAPIError(
            f"Failed to export template '{tmpl_name}' from '{project_name}'.", e
        ) from e


def import_template_to_project(cc, project_name, template):
    """
    Import (push) a template into a Catalyst Center project.
    IDs are stripped before import. The task is polled until completion.

    :param cc: DNACenterAPI instance.
    :param project_name: Target project name.
    :param template: Template details dictionary.
    :raises ProjectMissingError: If the target project does not exist.
    :raises CatalystAPIError: If the import fails or times out.
    """
    try:
        clean_template = strip_template_ids(template)
        project = fetch_project_by_name(cc, project_name)
        if project is None:
            raise ProjectMissingError(
                f"Project '{project_name}' not found while importing template."
            )
        response = cc.configuration_templates.imports_the_templates_provided(
            project_name=project["name"],
            do_version=True,
            payload=[clean_template],
            active_validation=False,
        )
        task_id = response["response"]["taskId"]
        for _ in range(60):
            task_resp = cc.task.get_tasks_by_id(task_id)
            status = task_resp["response"]["status"]
            logger.info(f"Task Status: {status}")
            if status == "SUCCESS":
                logger.info("Template imported successfully.")
                return
            elif status == "FAILURE":
                raise CatalystAPIError(
                    f"Failed to import template "
                    f"'{clean_template.get('name', '')}' "
                    f"into project '{project_name}'."
                )
            elif status == "PENDING":
                time.sleep(0.5)
            else:
                raise CatalystAPIError(f"Unexpected task status: {status}")
        raise CatalystAPIError(
            f"Timeout waiting for import of "
            f"'{clean_template.get('name', '')}' "
            f"into project '{project_name}'."
        )
    except (ProjectMissingError, CatalystAPIError):
        raise
    except Exception as e:
        logger.exception(
            f"Error importing template into project '{project_name}'."
        )
        raise CatalystAPIError(
            f"Error importing template into project '{project_name}'.", e
        ) from e


# ---------------------------------------------------------------------------
# GitHub API functions
# ---------------------------------------------------------------------------

GH_TOKEN = os.getenv("GITHUB_TOKEN")
GH_API_BASE = os.getenv(
    "GITHUB_REPO_API",
    "https://api.github.com/repos/prajravi/catalyst-template-library",
)
GH_COMMITS_URL = f"{GH_API_BASE}/commits"


def _auth_headers():
    """
    Build authorization headers for GitHub API requests.

    :return: Dictionary with Authorization header.
    :raises GitHubAPIError: If GITHUB_TOKEN is not set.
    """
    token = os.getenv("GITHUB_TOKEN") or GH_TOKEN
    if not token:
        raise GitHubAPIError("GITHUB_TOKEN environment variable is not set.")
    return {"Authorization": f"Bearer {token}"}


def fetch_head_commit_sha(branch=None):
    """
    Retrieve the latest commit SHA from the template library repository.

    :param branch: Optional branch name. Uses default branch if None.
    :return: Latest commit SHA string.
    :raises GitHubAPIError: If the request fails.
    """
    headers = _auth_headers()
    params = {}
    if branch:
        params["sha"] = branch
        logger.info(f"Fetching head commit for branch: {branch}")
    else:
        logger.info("Fetching head commit for default branch.")

    try:
        resp = requests.get(
            GH_COMMITS_URL, headers=headers, params=params, timeout=30
        )
        resp.raise_for_status()
        sha = resp.json()[0]["sha"]
        logger.info(f"Head commit SHA: {sha}")
        return sha
    except requests.exceptions.RequestException as e:
        branch_msg = f" for branch '{branch}'" if branch else ""
        logger.exception(f"Failed to fetch head commit{branch_msg}.")
        raise GitHubAPIError(
            f"Failed to fetch head commit{branch_msg}.", e
        ) from e


def fetch_commit_info(commit_sha):
    """
    Retrieve full commit data for a given SHA.

    :param commit_sha: The commit SHA to look up.
    :return: Commit data dictionary from the GitHub API.
    :raises GitHubAPIError: If the SHA is empty or the request fails.
    """
    if not commit_sha:
        raise GitHubAPIError("commit_sha must be provided and cannot be empty.")

    url = f"{GH_COMMITS_URL}/{commit_sha}"
    headers = _auth_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info(f"Commit info retrieved for SHA: {commit_sha}")
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.exception(f"Failed to fetch commit info for SHA '{commit_sha}'.")
        raise GitHubAPIError(
            f"Failed to fetch commit info for SHA '{commit_sha}'.", e
        ) from e


def get_modified_files_in_commit(commit_sha):
    """
    List files changed in a specific commit.

    :param commit_sha: The commit SHA.
    :return: List of file dictionaries (filename, status, contents_url, ...).
    :raises GitHubAPIError: If the commit has no files or the request fails.
    """
    data = fetch_commit_info(commit_sha)
    if "files" not in data:
        raise GitHubAPIError(
            f"No 'files' key in commit data for SHA '{commit_sha}'."
        )
    logger.info(
        f"Changed files in {commit_sha}: "
        f"{[f['filename'] for f in data['files']]}"
    )
    return data["files"]


def retrieve_file_content(file_entry):
    """
    Download and decode the content of a file from GitHub.

    :param file_entry: File dictionary from commit data (must include 'contents_url').
    :return: Decoded file content as a UTF-8 string.
    :raises GitHubAPIError: If contents_url is missing or download fails.
    """
    contents_url = file_entry.get("contents_url")
    if not contents_url:
        raise GitHubAPIError(
            "File entry does not contain a 'contents_url' key."
        )
    headers = _auth_headers()
    try:
        resp = requests.get(contents_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") == "base64":
            try:
                decoded = base64.b64decode(data["content"]).decode("utf-8")
                logger.info(
                    f"Decoded content for "
                    f"'{file_entry.get('filename', 'unknown')}'."
                )
                return decoded
            except Exception as e:
                raise GitHubAPIError(
                    f"Failed to decode content for "
                    f"'{file_entry.get('filename', 'unknown')}'.",
                    e,
                ) from e
        return data["content"]
    except requests.exceptions.RequestException as e:
        logger.exception(f"Failed to download file from {contents_url}.")
        raise GitHubAPIError(
            f"Failed to download file from {contents_url}.", e
        ) from e


def get_modified_files_in_branch(branch, base_branch="main"):
    """
    Get all files changed in a branch relative to the base branch.
    Uses the GitHub compare API.

    :param branch: Feature branch name.
    :param base_branch: Base branch to compare against (default: 'main').
    :return: List of changed-file dictionaries.
    :raises GitHubAPIError: If the comparison fails.
    """
    if not branch:
        raise GitHubAPIError("branch must be provided and cannot be empty.")

    try:
        branch_sha = fetch_head_commit_sha(branch)
        base_sha = fetch_head_commit_sha(base_branch)

        compare_url = f"{GH_API_BASE}/compare/{base_sha}...{branch_sha}"
        headers = _auth_headers()

        logger.info(f"Comparing {base_branch}...{branch}")
        resp = requests.get(compare_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "files" not in data:
            logger.warning(
                f"No files changed in '{branch}' vs '{base_branch}'."
            )
            return []

        files = data["files"]
        logger.info(
            f"Found {len(files)} changed files in "
            f"'{branch}' vs '{base_branch}'."
        )
        return files

    except requests.exceptions.RequestException as e:
        logger.exception(
            f"Failed to compare '{branch}' against '{base_branch}'."
        )
        raise GitHubAPIError(
            f"Failed to compare '{branch}' against '{base_branch}'.", e
        ) from e
    except GitHubAPIError:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error comparing branch '{branch}'.")
        raise GitHubAPIError(
            f"Unexpected error comparing branch '{branch}'.", e
        ) from e
