"""
Template helpers for alred.
"""

from __future__ import annotations

from typing import Any, Dict, List

from jinja2 import Environment

from .resources import get_resource_dir


_JINJA_ENV = Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

_TEMPLATE_DIR = get_resource_dir("j2")


def load_template_text(template_name: str) -> str:
    """
    Load a template file from the bundled Jinja2 template directory.
    """
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def render_template_lines(template_text: str, context: Dict[str, Any]) -> List[str]:
    """
    Render a Jinja2 template and return config lines without leading/trailing blank lines.
    """
    rendered = _JINJA_ENV.from_string(template_text).render(**context)
    return [line for line in rendered.strip().splitlines()] if rendered.strip() else []


def render_named_template_lines(template_name: str, context: Dict[str, Any]) -> List[str]:
    """
    Load and render a named template file.
    """
    return render_template_lines(load_template_text(template_name), context)
