from __future__ import annotations

import functools
from collections import defaultdict


class HookManager:
    """Simple in-process hook registry and dispatcher.

    Hooks are stored under an arbitrary `hook_key`. Callers register callbacks via `register()`
    and trigger them via `dispatch()`.
    """

    def __init__(self):
        self._hooks = defaultdict(list)

    def register(self, hook_key, func):
        self._hooks[hook_key].append(func)

    def dispatch(self, hook_key, *args, **kwargs):
        for func in self._hooks[hook_key]:
            func(*args, **kwargs)

    def has(self, hook_key, func=None) -> bool:
        """Check whether a hook key has any callbacks registered.

        Args:
            hook_key: Hook key used during `register()` and `dispatch()`.
            func: Optional specific callback to test membership.

        Returns:
            True if there is at least one callback for `hook_key`, or if `func` is provided
            and it is registered under `hook_key`.
        """
        hooks = self._hooks.get(hook_key, [])
        if func is None:
            return bool(hooks)
        return func in hooks


class HookStage:
    """A hook stage with BEFORE/AFTER/ERROR keys derived from a stage name."""

    def __init__(self, stage_name: str):
        self._stage_name = stage_name
        self.BEFORE = (stage_name, "before")
        self.AFTER = (stage_name, "after")
        self.ERROR = (stage_name, "error")

    def __repr__(self):
        return f"<HookStage: {self._stage_name}>"


def masf_hook(stage_obj: HookStage):
    """Decorator that dispatches BEFORE/AFTER/ERROR hooks around a method call.

    Args:
        stage_obj: HookStage that defines the BEFORE/AFTER/ERROR keys used for dispatch.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, "hooks") or not isinstance(self.hooks, HookManager):
                raise AttributeError(
                    f"{type(self).__name__} must have a 'hooks' attribute of type HookManager."
                )
            self.hooks.dispatch(stage_obj.BEFORE, self, *args, **kwargs)
            try:
                result = func(self, *args, **kwargs)
            except Exception as err:
                self.hooks.dispatch(stage_obj.ERROR, self, err, *args, **kwargs)
                raise
            self.hooks.dispatch(stage_obj.AFTER, self, result, *args, **kwargs)
            return result

        return wrapper

    return decorator


__all__ = ["HookManager", "HookStage", "masf_hook"]
