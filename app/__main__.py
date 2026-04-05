"""
Network Template GitOps -- main entry point.

Pipeline stages:
  1. validate-stage  -- Verify templates exist in the Stage project.
  2. validate-prod   -- Verify the Prod project exists.
  3. drift-check     -- Compare Git content against Stage content (must match).
  4. promote         -- Export from Stage, import into Prod.

Repository layout: <project_folder>/<template_name>.j2
A single Catalyst Center hosts two projects per folder, using configurable
'-stage' and '-prod' suffixes (see settings.yaml).
"""

import argparse
import logging
import yaml

from dotenv import load_dotenv

from app.utils import (
    init_catc_connection,
    fetch_project_by_name,
    list_templates_in_project,
    export_template_from_project,
    import_template_to_project,
    get_modified_files_in_commit,
    retrieve_file_content,
    get_modified_files_in_branch,
    sha256_hash,
    content_is_equal,
)
from app.error_handler import (
    CatalystAPIError,
    ContentDriftError,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Logging setup (inline -- no separate module)
# ---------------------------------------------------------------------------

LOG_FORMAT = (
    'lineno="%(lineno)d" asctime="%(asctime)s" name="%(name)s" '
    'levelname="%(levelname)s" message="%(message)s"'
)


def _configure_logging():
    """
    Configure the root logger with a console handler and standard format.
    Called once at startup so every module inherits the same configuration.
    """
    root = logging.getLogger()
    if not root.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        )
        root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def read_config():
    """
    Load pipeline settings from settings.yaml.

    :return: Dictionary with stage_suffix, prod_suffix, template_folders.
    """
    try:
        with open("settings.yaml", "r") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        logger.warning(f"Could not load settings.yaml: {e}. Using defaults.")
        return {}


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_arg_parser():
    """
    Parse command-line arguments.

    :return: argparse.Namespace with commit, branch, and stage.
    """
    parser = argparse.ArgumentParser(
        description="Network Template GitOps - Promote templates from Stage to Prod"
    )
    parser.add_argument(
        "--commit", type=str, help="Commit SHA to process", default=None
    )
    parser.add_argument(
        "--branch", type=str, help="Branch name to process", default="main"
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["validate-stage", "validate-prod", "drift-check", "promote"],
        help="Pipeline stage to execute",
        default="promote",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def map_project_names(folder_name, config):
    """
    Derive the Stage and Prod project names from a Git repository folder name.

    :param folder_name: Top-level folder name in the Git repo.
    :param config: Pipeline configuration dictionary.
    :return: Tuple (stage_project_name, prod_project_name).
    """
    stage_sfx = config.get("stage_suffix", "-stage")
    prod_sfx = config.get("prod_suffix", "-prod")
    return f"{folder_name}{stage_sfx}", f"{folder_name}{prod_sfx}"


def fetch_changed_files(commit_sha, branch):
    """
    Retrieve the list of changed files from GitHub.
    For 'main' branch uses the specific commit; for feature branches compares
    all changes against main.

    :param commit_sha: Commit SHA (required when branch is 'main').
    :param branch: Branch name being processed.
    :return: List of changed-file dictionaries.
    :raises CatalystAPIError: If retrieval fails.
    """
    try:
        if branch == "main":
            if not commit_sha:
                raise CatalystAPIError(
                    "Commit SHA is required when branch is 'main'."
                )
            return get_modified_files_in_commit(commit_sha)
        else:
            return get_modified_files_in_branch(branch)
    except CatalystAPIError:
        raise
    except Exception as e:
        logger.exception(f"Failed to fetch changed files: {e}")
        raise CatalystAPIError(
            f"Failed to fetch changed files: {e}"
        ) from e


def parse_repo_path(path):
    """
    Extract the project folder and template name from a repo file path.
    Expected format: <project_folder>/<template_name>.j2

    :param path: File path string from GitHub commit data.
    :return: Tuple (project_folder, template_name) or (None, None) if invalid.
    """
    if "/" not in path:
        return None, None
    folder = path.split("/")[0]
    filename = path.split("/")[-1]
    if not filename.endswith(".j2"):
        return folder, None
    return folder, filename.rsplit(".", 1)[0]


def is_template_in_project(cc, project_name, tmpl_name):
    """
    Check whether a template exists in a Catalyst Center project.

    :param cc: DNACenterAPI instance.
    :param project_name: Project name to search.
    :param tmpl_name: Template name to look for.
    :return: True if the template exists, False otherwise.
    """
    try:
        project = fetch_project_by_name(cc, project_name)
        if project is None:
            return False
        return any(
            t["name"] == tmpl_name
            for t in list_templates_in_project(project)
        )
    except Exception as e:
        logger.warning(
            f"Error checking template '{tmpl_name}' in '{project_name}': {e}"
        )
        return False


def handle_deleted_template(changed_file, tmpl_name, stage_proj_name, cc=None):
    """
    Handle a file that was deleted in Git.
    If the template still exists in the Stage project an error is raised,
    because it must be removed from Catalyst Center first.

    :param changed_file: File dictionary from commit data.
    :param tmpl_name: Template name derived from the path.
    :param stage_proj_name: Stage project name on Catalyst Center.
    :param cc: Optional DNACenterAPI instance for existence check.
    :return: True if deleted and safe to skip, False if not deleted.
    :raises CatalystAPIError: If deleted in Git but present in Catalyst Center.
    """
    if changed_file.get("status") != "removed":
        return False

    if cc is not None and is_template_in_project(cc, stage_proj_name, tmpl_name):
        msg = (
            f"Template '{tmpl_name}' is deleted in Git but still exists in "
            f"Catalyst Center project '{stage_proj_name}'. "
            f"Remove it from Stage first."
        )
        logger.error(msg)
        raise CatalystAPIError(msg)

    logger.info(
        f"Skipping deleted template: {tmpl_name} in {stage_proj_name}"
    )
    return True


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def stage_validation(commit_sha, branch, config):
    """
    Verify that every changed template exists in the Stage project
    on Catalyst Center.

    :param commit_sha: Commit SHA (required for main branch).
    :param branch: Branch being processed.
    :param config: Pipeline configuration dictionary.
    :raises CatalystAPIError: If any template cannot be found in Stage.
    """
    cc = init_catc_connection()
    changed_files = fetch_changed_files(commit_sha, branch)

    for changed_file in changed_files:
        folder, tmpl_name = parse_repo_path(changed_file["filename"])
        if folder is None or tmpl_name is None:
            continue

        stage_proj_name, _ = map_project_names(folder, config)

        if handle_deleted_template(changed_file, tmpl_name, stage_proj_name, cc):
            continue

        try:
            export_template_from_project(cc, stage_proj_name, tmpl_name)
            logger.info(
                f"Stage validation OK: {tmpl_name} in {stage_proj_name}"
            )
        except Exception as e:
            logger.exception(
                f"Stage validation FAILED: "
                f"{tmpl_name} in {stage_proj_name}: {e}"
            )
            raise CatalystAPIError(
                f"Stage validation failed for "
                f"{tmpl_name} in {stage_proj_name}: {e}"
            ) from e


def prod_validation(commit_sha, branch, config):
    """
    Verify that the Prod project exists for every changed template's folder.

    :param commit_sha: Commit SHA (required for main branch).
    :param branch: Branch being processed.
    :param config: Pipeline configuration dictionary.
    :raises CatalystAPIError: If any Prod project is missing.
    """
    cc = init_catc_connection()
    changed_files = fetch_changed_files(commit_sha, branch)

    for changed_file in changed_files:
        folder, tmpl_name = parse_repo_path(changed_file["filename"])
        if folder is None or tmpl_name is None:
            continue

        _, prod_proj_name = map_project_names(folder, config)

        project = fetch_project_by_name(cc, prod_proj_name)
        if project is None:
            raise CatalystAPIError(
                f"Prod project '{prod_proj_name}' does not exist "
                f"on Catalyst Center."
            )
        logger.info(f"Prod validation OK: project '{prod_proj_name}' exists.")


def drift_analysis(commit_sha, branch, config):
    """
    Verify template content in Git matches Stage on Catalyst Center.
    Also rejects non-.j2 files in template folders.

    :param commit_sha: Commit SHA (required for main branch).
    :param branch: Branch being processed.
    :param config: Pipeline configuration dictionary.
    :raises ContentDriftError: If non-.j2 files found or content diverges.
    :raises CatalystAPIError: If an API operation fails.
    """
    cc = init_catc_connection()
    changed_files = fetch_changed_files(commit_sha, branch)
    allowed_folders = config.get("template_folders", [])

    # Reject non-.j2 files in template folders
    bad_files = []
    for f in changed_files:
        path = f["filename"]
        folder = path.split("/")[0] if "/" in path else ""
        if folder in allowed_folders and not path.split("/")[-1].endswith(".j2"):
            bad_files.append(path)
    if bad_files:
        for bf in bad_files:
            logger.error(
                f"Non '.j2' file committed in template folder: {bf}"
            )
        raise ContentDriftError(
            f"Non '.j2' file(s) in template folder(s): "
            f"{', '.join(bad_files)}"
        )

    # Content comparison
    for changed_file in changed_files:
        folder, tmpl_name = parse_repo_path(changed_file["filename"])
        if folder is None or tmpl_name is None:
            continue

        stage_proj_name, _ = map_project_names(folder, config)

        if handle_deleted_template(
            changed_file, tmpl_name, stage_proj_name, cc
        ):
            continue

        try:
            tmpl_data = export_template_from_project(
                cc, stage_proj_name, tmpl_name
            )
            git_body = retrieve_file_content(changed_file)
            stage_body = tmpl_data["templateContent"]

            if content_is_equal(git_body, stage_body):
                logger.info(
                    f"Drift check OK: {tmpl_name} in {stage_proj_name}"
                )
            else:
                logger.error(
                    f"Drift detected for {tmpl_name} in {stage_proj_name}. "
                    f"Git hash: {sha256_hash(git_body)}, "
                    f"Stage hash: {sha256_hash(stage_body)}"
                )
                raise ContentDriftError(
                    f"Content mismatch for '{tmpl_name}' "
                    f"in '{stage_proj_name}'."
                )
        except (ContentDriftError, CatalystAPIError):
            raise
        except Exception as e:
            logger.exception(f"Drift check failed for {tmpl_name}: {e}")
            raise CatalystAPIError(
                f"Drift check failed for {tmpl_name}: {e}"
            ) from e


def promote_to_production(commit_sha, branch, config):
    """
    Promote templates from Stage to Prod.
    For each changed file: export from Stage, import into Prod.

    :param commit_sha: Commit SHA (required for main branch).
    :param branch: Branch being processed.
    :param config: Pipeline configuration dictionary.
    :raises CatalystAPIError: If any export or import fails.
    """
    cc = init_catc_connection()
    changed_files = fetch_changed_files(commit_sha, branch)

    for changed_file in changed_files:
        folder, tmpl_name = parse_repo_path(changed_file["filename"])
        if folder is None or tmpl_name is None:
            continue

        stage_proj_name, prod_proj_name = map_project_names(folder, config)

        logger.info(
            f"Processing: folder={folder}, template={tmpl_name}, "
            f"status={changed_file.get('status')}"
        )

        if handle_deleted_template(
            changed_file, tmpl_name, stage_proj_name, cc
        ):
            continue

        file_status = changed_file.get("status", "")
        if file_status not in ("modified", "added", "renamed"):
            logger.info(
                f"Unhandled file status '{file_status}' "
                f"for {tmpl_name}. Skipping."
            )
            continue

        if file_status == "renamed":
            logger.warning(
                f"Template '{tmpl_name}' was renamed. Update composite "
                f"template references manually if needed."
            )

        try:
            tmpl_data = export_template_from_project(
                cc, stage_proj_name, tmpl_name
            )
            import_template_to_project(cc, prod_proj_name, tmpl_data)
            logger.info(
                f"Promoted '{tmpl_name}' from "
                f"'{stage_proj_name}' to '{prod_proj_name}'."
            )
        except Exception as e:
            logger.exception(
                f"Failed to promote '{tmpl_name}' from "
                f"'{stage_proj_name}' to '{prod_proj_name}': {e}"
            )
            raise CatalystAPIError(
                f"Failed to promote '{tmpl_name}': {e}"
            ) from e


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_pipeline():
    """Main entry point. Dispatches to the requested pipeline stage."""
    args = build_arg_parser()
    commit_sha = args.commit
    branch = args.branch
    config = read_config()

    logger.info(f"Pipeline started -- stage={args.stage}, branch={branch}")

    try:
        if args.stage == "validate-stage":
            stage_validation(commit_sha, branch, config)
        elif args.stage == "validate-prod":
            prod_validation(commit_sha, branch, config)
        elif args.stage == "drift-check":
            drift_analysis(commit_sha, branch, config)
        elif args.stage == "promote":
            promote_to_production(commit_sha, branch, config)

        logger.info(
            f"Pipeline stage '{args.stage}' completed successfully."
        )
    except Exception as e:
        logger.error(f"Pipeline stage '{args.stage}' failed: {e}")
        raise


if __name__ == "__main__":
    run_pipeline()
