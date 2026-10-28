"""How an approver proved who they are, as recorded on an approval (B-89, C-44).

`ApproverAuth` is what the queue keeps on a decided proposal and what a reject's audit record
carries: the sign-in method, the repo identity, the Entra object id and tenant, the authentication
methods (`amr`) and the session id (`sid`), and the token's issue and expiry times. It never holds
the token, a signature or a key (STD-AU-4 item 1). A demo decision is `demo-picker` with no claims,
so it can never be mistaken for a signed-in one.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, model_validator

AuthMethod = Literal["entra-id-token", "demo-picker"]
IdentityId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
Guid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
AmrValue = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{1,32}$")]
SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,64}$")]
UtcStamp = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]


class ApproverAuth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: AuthMethod
    identity: IdentityId
    oid: Guid | None = None
    tid: Guid | None = None
    amr: tuple[AmrValue, ...] = ()
    sid: SessionId | None = None
    issued_at: UtcStamp | None = None
    expires_at: UtcStamp | None = None
    note: StrictStr = ""

    @model_validator(mode="after")
    def _method_matches_claims(self) -> ApproverAuth:
        claims = (self.oid, self.tid, self.sid, self.issued_at, self.expires_at)
        if self.method == "entra-id-token":
            if any(c is None for c in claims) or not self.amr:
                raise ValueError("an entra-id-token sign-in needs oid, tid, amr, sid, issued_at and expires_at")
        elif any(c is not None for c in claims) or self.amr:
            raise ValueError("a demo-picker sign-in carries no token claims")
        return self

    @classmethod
    def demo(cls, identity: str) -> ApproverAuth:
        """The record of a decision made through the demo picker (STD-ID-7): not authentication."""
        return cls(method="demo-picker", identity=identity, note="demo sign-in, synthetic data, not authentication")
