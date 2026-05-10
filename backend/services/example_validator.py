"""Email validation utilities."""

import re


def validate_email(email: str) -> bool:
    """Validate an email address using a regex pattern.

    Args:
        email: The email address to validate.

    Returns:
        True if the email is valid, False otherwise.
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
