"""Backward-compatible import location for the shared attribute firewall."""

from ..attribute_firewall import (
    assert_explicit_attribute_policies,
    iter_owned_nodes,
    seal_loop_attributes,
)

__all__ = ["assert_explicit_attribute_policies", "iter_owned_nodes", "seal_loop_attributes"]
