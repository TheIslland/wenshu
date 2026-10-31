"""API router registry. Keep this list stable so workstreams never edit app.py."""

from . import (
    citations,
    direction,
    documents,
    export,
    health,
    library,
    methods,
    paragraphs,
    polish,
    projects,
    search,
    settings,
    style,
    workflow,
)

ROUTERS = [
    health,
    projects,
    documents,
    search,
    library,
    style,
    polish,
    paragraphs,
    methods,
    direction,
    workflow,
    citations,
    export,
    settings,
]
