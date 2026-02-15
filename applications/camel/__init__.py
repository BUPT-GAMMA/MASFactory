"""CAMEL Role-Playing Application.

This package provides a CAMEL (Communicative Agents for "Mind" Exploration of Large Language Model Society)
role-playing implementation using the MASFactory framework.
"""

from .workflow import create_camel_role_playing_workflow
from .main import main

__all__ = ["create_camel_role_playing_workflow", "main"]
