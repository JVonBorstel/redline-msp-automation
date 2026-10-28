"""Affected-person notice drafts (B-04): after an executed write lever, a plain-words draft a person sends (HO-9).

path = notice_for(Path(".tmp/demo"), "P-0123456789ab")   # writes .tmp/demo/notices/P-0123456789ab.md
"""

from workflows.notify.notify import (
    DEFAULT_CONTACTS_PATH,
    DRAFT_HEADER,
    TEMPLATES_DIR,
    Notice,
    NotifyError,
    NotifyRefused,
    draft_notice,
    load_contacts,
    load_proposal,
    missing_templates,
    notice_for,
    template_path,
    write_notice,
)

__all__ = [
    "DEFAULT_CONTACTS_PATH",
    "DRAFT_HEADER",
    "TEMPLATES_DIR",
    "Notice",
    "NotifyError",
    "NotifyRefused",
    "draft_notice",
    "load_contacts",
    "load_proposal",
    "missing_templates",
    "notice_for",
    "template_path",
    "write_notice",
]
