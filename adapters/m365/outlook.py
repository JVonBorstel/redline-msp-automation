"""Outlook draft builder (B-88, B88-2). MOCK; no mailbox is touched. It creates a DRAFT and has no way to deliver one.

UNVERIFIED: the message shape (``subject``, ``body`` with ``contentType`` and ``content``, ``toRecipients`` of
``emailAddress.address``, ``isDraft``) was written from memory; no Microsoft page was opened and no call was made.
The mock id is derived from the content and is not a Graph id.

The weekly digest is given to this builder as structured lines (the digest itself is not built in this item). Rules,
all fail closed:

- The draft is created for a technician's mailbox to review; this class offers create, list and get, and nothing that
  delivers a message. A test reads the module to keep it that way.
- Recipients must be addresses on the client's own domains, passed in by the caller (none given means none allowed),
  at most 10, one plain address each; a display name, a list in one string or a line break is refused.
- The subject is built from the client id and the week only. Digest lines never reach a header.
- The body is plain text. A line that reads like an instruction is withheld; a line holding a secret-shaped value
  refuses the whole draft (the value is never echoed); other personal data is replaced by typed placeholders (B-55).
- Dry run is the default (docs/BLUEPRINT.md rule 5): the payload is returned and nothing is stored.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from adapters.base import Adapter, AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from adapters.m365.text import WITHHELD, one_line
from core.guard.detect import detect_injection
from core.guard.redact_prompt import redact_prompt

Record = dict[str, Any]

MAX_RECIPIENTS = 10
MAX_ITEMS = 50
MAX_ITEM_CHARS = 300
MAX_ITEM_INPUT = 5000
DRAFT_BANNER = "DRAFT - not delivered. A person reviews this in Outlook and decides whether to deliver it."
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]{1,64}@([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)")
_DOMAIN = re.compile(r"[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+")


class OutlookDraftMock(Adapter):
    """Draft store for one client's digests. In memory; the process owns it."""

    system = "m365"

    def __init__(self, client: str, binding: BoundBinding, *, allowed_domains: Sequence[str] = ()) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("OutlookDraftMock serves the 'mock' implementation only")
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        domains = {d.strip().lower() for d in allowed_domains}
        if not all(_DOMAIN.fullmatch(d) for d in domains):
            raise AdapterError("allowed_domains holds something that is not a domain name")
        self._domains = frozenset(domains)
        self._drafts: dict[str, Record] = {}

    def create_digest_draft(
        self,
        *,
        week_of: str,
        mailbox: str,
        to: Sequence[str],
        items: Sequence[str],
        dry_run: bool = True,
    ) -> AdapterResult[Record]:
        """Build the weekly digest draft; store it unless ``dry_run``. Never raises (STD-ER-1)."""
        return self._guard(lambda: self._create(week_of, mailbox, to, items, dry_run))

    def list_drafts(self) -> AdapterResult[list[Record]]:
        return self._guard(
            lambda: AdapterResult.success([copy.deepcopy(self._drafts[k]) for k in sorted(self._drafts)])
        )

    def get_draft(self, draft_id: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            found = self._drafts.get(draft_id)
            return AdapterResult.success(copy.deepcopy(found)) if found else AdapterResult.failure("no such draft")

        return self._guard(run)

    # -- internals ------------------------------------------------------------------------

    def _recipients(self, to: Sequence[str]) -> list[str] | str:
        if isinstance(to, str) or not 1 <= len(to) <= MAX_RECIPIENTS:
            return f"between 1 and {MAX_RECIPIENTS} recipients are needed"
        found: list[str] = []
        for address in to:
            match = _ADDRESS.fullmatch(address) if isinstance(address, str) else None
            if match is None:
                return "a recipient is not a single plain address"
            if match.group(1).lower() not in self._domains:
                return "a recipient is outside this client's own domains"
            if address.lower() not in found:
                found.append(address.lower())
        return found

    def _lines(self, items: Sequence[str]) -> list[str] | str:
        if isinstance(items, str) or not 1 <= len(items) <= MAX_ITEMS:
            return f"between 1 and {MAX_ITEMS} digest lines are needed"
        lines: list[str] = []
        for item in items:
            if not isinstance(item, str):
                return "a digest line is not text"
            raw = item[:MAX_ITEM_INPUT]
            gate = redact_prompt(raw)
            if gate.blocked:
                return "a digest line holds a secret-shaped value; draft refused"
            lines.append(WITHHELD if detect_injection(raw).flagged else one_line(gate.text, MAX_ITEM_CHARS))
        return lines

    def _create(
        self, week_of: str, mailbox: str, to: Sequence[str], items: Sequence[str], dry_run: bool
    ) -> AdapterResult[Record]:
        try:
            datetime.date.fromisoformat(week_of)
        except (TypeError, ValueError):
            return AdapterResult.failure("week_of must be a real YYYY-MM-DD date")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_of):
            return AdapterResult.failure("week_of must be a real YYYY-MM-DD date")
        if not isinstance(mailbox, str) or _ADDRESS.fullmatch(mailbox) is None:
            return AdapterResult.failure("mailbox is not a single plain address")
        recipients = self._recipients(to)
        if isinstance(recipients, str):
            return AdapterResult.failure(recipients)
        lines = self._lines(items)
        if isinstance(lines, str):
            return AdapterResult.failure(lines)

        subject = f"Weekly IT summary for {self.client}, week of {week_of}"
        content = "\n".join([DRAFT_BANNER, "", f"Weekly IT summary, week of {week_of}", "", *(f"- {x}" for x in lines)])
        message: Record = {
            "subject": subject,
            "body": {"contentType": "text", "content": content},
            "toRecipients": [{"emailAddress": {"address": a}} for a in recipients],
            "from": {"emailAddress": {"address": mailbox.lower()}},
            "isDraft": True,
        }
        digest = hashlib.sha256(json.dumps([self.client, message], sort_keys=True).encode("utf-8")).hexdigest()
        message["id"] = "MOCK-DRAFT-" + digest[:16]
        if dry_run:
            return AdapterResult.success(message, "dry-run: no draft was created")
        self._drafts[message["id"]] = copy.deepcopy(message)
        return AdapterResult.success(message, "draft created in the mock mailbox; nothing was delivered")
