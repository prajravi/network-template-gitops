"""
Custom exception classes for Network Template GitOps.
Each exception covers a specific failure domain for precise error handling.
"""


class AuthenticationError(Exception):
    """Raised when authentication to Catalyst Center fails."""

    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.original_exception = original_exception


class ProjectMissingError(Exception):
    """Raised when a project is not found in Catalyst Center."""

    def __init__(self, project_name):
        super().__init__(f"Project '{project_name}' not found.")


class CatalystAPIError(Exception):
    """Raised when a Catalyst Center API operation fails."""

    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.original_exception = original_exception


class GitHubAPIError(Exception):
    """Raised when a GitHub API operation fails."""

    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.original_exception = original_exception


class ContentDriftError(Exception):
    """Raised when template content in Git does not match Catalyst Center."""

    def __init__(self, message, original_exception=None):
        super().__init__(message)
        self.original_exception = original_exception
