"""Technology roadmap recommendations and the client AI-use policy draft (B-73). Drafts only; nothing is sent.

road = build_roadmap("contoso-dental", "2026-10", generated_on="2026-10-31")      # items, each with cited findings
policy = build_ai_policy("contoso-dental", generated_on="2026-10-31")             # the filled starter policy
drafts = create_drafts("contoso-dental", "2026-10", generated_on="2026-10-31", out_dir=Path("build/client-roadmap"))
"""

from workflows.reporting.roadmap.ai_policy import AIPolicyDraft, ClassRow, HostedStatus, Tool, build_ai_policy
from workflows.reporting.roadmap.drafts import (
    Drafts,
    create_drafts,
    main,
    render_policy,
    render_roadmap,
    roadmap_to_dict,
    verify_draft,
    verify_roadmap,
)
from workflows.reporting.roadmap.model import (
    Budget,
    Evidence,
    FileRef,
    Recommendation,
    Roadmap,
    RoadmapError,
    VerifyError,
)
from workflows.reporting.roadmap.recommend import build_roadmap

__all__ = [
    "AIPolicyDraft",
    "Budget",
    "ClassRow",
    "Drafts",
    "Evidence",
    "FileRef",
    "HostedStatus",
    "Recommendation",
    "Roadmap",
    "RoadmapError",
    "Tool",
    "VerifyError",
    "build_ai_policy",
    "build_roadmap",
    "create_drafts",
    "main",
    "render_policy",
    "render_roadmap",
    "roadmap_to_dict",
    "verify_draft",
    "verify_roadmap",
]
