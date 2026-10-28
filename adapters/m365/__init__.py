"""Microsoft 365 mocks (B-88): Teams approval card, Outlook draft builder, SharePoint ingestion source.

All three are mocks that fail closed. Payload shapes are UNVERIFIED against Microsoft documentation
(see ``specs/B-88.md``).
Nothing here calls a network, holds a credential, sends a message or decides an approval.
"""

from __future__ import annotations

from adapters.m365.outlook import OutlookDraftMock
from adapters.m365.sharepoint import SharePointIngestReport, SharePointMock, ingest_sharepoint
from adapters.m365.teams_card import CardError, CardResponseResult, build_approval_card, handle_card_response

__all__ = [
    "CardError",
    "CardResponseResult",
    "OutlookDraftMock",
    "SharePointIngestReport",
    "SharePointMock",
    "build_approval_card",
    "handle_card_response",
    "ingest_sharepoint",
]
