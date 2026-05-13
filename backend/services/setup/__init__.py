"""Setup and preflight-check sub-package."""

from backend.services.setup.checks import (
    AgentAuthStatus,
    AgentCLIStatus,
    check_agent_auth,
    check_agent_cli,
    find_cpl_processes,
)
from backend.services.setup.service import (
    diagnose_configuration,
    execute_setup_wizard,
    validate_preflight,
)

__all__ = [
    "AgentAuthStatus",
    "AgentCLIStatus",
    "check_agent_auth",
    "check_agent_cli",
    "diagnose_configuration",
    "execute_setup_wizard",
    "find_cpl_processes",
    "validate_preflight",
]
