from __future__ import annotations

from dataclasses import dataclass, field

from .policy import ContextPolicy, DefaultContextPolicy, ProviderBlocks
from .provider import ContextProvider, HistoryProvider
from .renderer import ContextRenderer, DefaultContextRenderer
from .types import ContextQuery


@dataclass(slots=True)
class ContextComposer:
    """Collect context blocks from providers and inject them into the user payload."""

    providers: list[ContextProvider]
    history_providers: list[HistoryProvider] = field(default_factory=list)
    policy: ContextPolicy = DefaultContextPolicy()
    renderer: ContextRenderer = DefaultContextRenderer()

    def inject_user_payload(self, user_payload: dict, query: ContextQuery, *, top_k: int = 8) -> dict:
        provider_blocks = self._collect_provider_blocks(query, top_k=top_k)
        selected = self.policy.select(provider_blocks, top_k=top_k)
        return self.renderer.inject(user_payload, selected)

    def get_history_messages(self, query: ContextQuery, *, top_k: int = -1) -> list[dict]:
        """Collect and deduplicate history messages from history providers."""
        if not self.history_providers:
            return []
        messages: list[dict] = []
        for provider in self.history_providers:
            try:
                batch = provider.get_messages(query, top_k=top_k) or []
            except Exception:
                batch = []
            for msg in batch:
                if isinstance(msg, dict):
                    messages.append(msg)
        # Stable dedupe (dict equality), preserve order.
        unique: list[dict] = []
        for msg in messages:
            if msg not in unique:
                unique.append(msg)
        return unique

    def _collect_provider_blocks(self, query: ContextQuery, *, top_k: int) -> list[ProviderBlocks]:
        results: list[ProviderBlocks] = []
        for provider in self.providers:
            label = self._provider_label(provider)
            try:
                blocks = provider.get_blocks(query, top_k=top_k) or []
            except Exception:
                blocks = []
            if blocks:
                results.append((label, blocks))
        return results

    def _provider_label(self, provider: ContextProvider) -> str:
        return getattr(provider, "context_label", provider.__class__.__name__)
