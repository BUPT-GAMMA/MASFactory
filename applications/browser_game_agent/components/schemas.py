"""
Structured schemas for Browser Game Agent phase outputs.

The app prefers Pydantic when it is installed, but keeps a tiny fallback so
utility modules can still be imported in lightweight MASFactory checkouts.
"""

from __future__ import annotations

from typing import Any, List

try:  # pragma: no cover - exercised when the web app dependencies are present.
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - fallback keeps local static checks usable.
    def Field(default=None, **kwargs):  # type: ignore
        if "default_factory" in kwargs:
            return kwargs["default_factory"]()
        return default

    class BaseModel:  # type: ignore
        def __init__(self, **kwargs):
            annotations = getattr(self, "__annotations__", {})
            for key, default in self.__class__.__dict__.items():
                if key.startswith("_") or callable(default):
                    continue
                if key in annotations:
                    setattr(self, key, kwargs.pop(key, default))
            for key in annotations:
                if not hasattr(self, key):
                    setattr(self, key, kwargs.pop(key, None))
            for key, value in kwargs.items():
                setattr(self, key, value)

        def model_dump(self) -> dict[str, Any]:
            return {
                key: getattr(self, key)
                for key in getattr(self, "__annotations__", {})
            }

        @classmethod
        def model_json_schema(cls) -> dict[str, Any]:
            return {"title": cls.__name__, "fields": list(getattr(cls, "__annotations__", {}).keys())}


class GamePlanSchema(BaseModel):
    title: str = Field(default="", description="Short game title.")
    game_type: str = Field(default="", description="Game genre/type.")
    mechanics: List[str] = Field(default_factory=list, description="Core mechanics.")
    entities: List[str] = Field(default_factory=list, description="Player, enemies, items, systems.")
    controls: List[str] = Field(default_factory=list, description="Controls and input bindings.")
    test_checkpoints: List[str] = Field(default_factory=list, description="Verifiable yes/no behaviors.")
    markdown: str = Field(default="", description="Full design document markdown.")


class BrowserCheckSchema(BaseModel):
    available: bool = Field(default=False, description="Whether the browser runner executed.")
    page_loaded: bool = Field(default=False)
    console_errors: List[str] = Field(default_factory=list)
    page_errors: List[str] = Field(default_factory=list)
    canvas_count: int = Field(default=0)
    canvas_nonblank: bool = Field(default=False)
    screenshot_changed_after_input: bool = Field(default=False)
    keyboard_events_dispatched: int = Field(default=0)
    screenshot_path: str = Field(default="")
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    details: str = Field(default="")


class TestResultSchema(BaseModel):
    round: int = Field(default=1)
    ui_passed: bool = Field(default=False)
    func_passed: bool = Field(default=False)
    both_passed: bool = Field(default=False)
    ui_issues: List[str] = Field(default_factory=list)
    functional_issues: List[str] = Field(default_factory=list)
    ui_report: str = Field(default="")
    functional_report: str = Field(default="")
    evidence: dict[str, Any] = Field(default_factory=dict)


class FixDecisionSchema(BaseModel):
    needs_fix: bool = Field(default=False)
    reason: str = Field(default="")
    changed_files: List[str] = Field(default_factory=list)
    summary: str = Field(default="")


class DocResultSchema(BaseModel):
    readme: str = Field(default="")
    implementation_doc: str = Field(default="")


class LessonSchema(BaseModel):
    """A single cross-session lesson: a recurring bug pattern and how to avoid/fix it."""
    pattern: str = Field(default="", description="Short name of the recurring bug/design pitfall.")
    symptom: str = Field(default="", description="Observable symptom (what the test/QA saw).")
    fix: str = Field(default="", description="Concrete fix or preventative measure that resolved it.")
    tags: List[str] = Field(default_factory=list, description="Keywords: game_type, subsystem, api, etc.")


class LessonListSchema(BaseModel):
    lessons: List[LessonSchema] = Field(default_factory=list, description="Distilled lessons from this session.")


def model_to_dict(model: Any) -> dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump()
    if isinstance(model, dict):
        return model
    return dict(getattr(model, "__dict__", {}))


def schema_as_text(model_cls: type[BaseModel]) -> str:
    schema = getattr(model_cls, "model_json_schema", None)
    if callable(schema):
        return str(schema())
    return str(getattr(model_cls, "__annotations__", {}))


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "pass", "passed", "ok"}
    return bool(value)
