"""Deterministic route marker; it is never invoked as an operator."""
class EarlyStop:
    name = "EarlyStop"

    def __call__(self, *_args, **_kwargs):
        raise NotImplementedError("EarlyStop is a control marker, not an operator")

__all__ = ["EarlyStop"]
