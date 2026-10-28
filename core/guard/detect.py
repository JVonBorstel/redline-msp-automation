"""Prompt-injection detector: transparent, rule-based heuristics over untrusted text.

Every rule is a named regex (or a small structural check) listed in ``RULES``, so a reviewer can read exactly
why something was flagged. Flagged input is reported, never obeyed: the detector only describes, it never acts.

Order of work for one input:
1. note invisible characters in the raw text (zero-width, bidi, tag characters), then normalise (strip + NFKC);
2. run the text rules over the normalised text, over the text with HTML entities and look-alike letters resolved,
   and over any text smuggled in Unicode tag characters;
3. run the structural rules (HTML comments, hiding styles, markdown image links with query strings);
4. decode base64-looking blobs and run the text rules over what they decode to.

This is a heuristic tripwire, not a guarantee. It is one layer; the lever registry's permission checks are the
real control, so a missed injection still cannot press a button its caller was not allowed to press.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from core.guard.normalise import decoded_variant, find_invisible, normalise, reveal_tag_text

_FLAGS = re.IGNORECASE | re.MULTILINE
_EVIDENCE_MAX = 90
_B64_MAX_BLOBS = 50
_B64_MAX_LEN = 16_384

# Free-text gaps between keywords are bounded ({0,N}) so hostile input cannot cause catastrophic backtracking.
# Reusable fragments.
_AI = r"(?:ai|assistant|agent|bot|chatbot|model|llm|copilot)"
_ALL_TARGETS = (
    r"(?:everyone|everybody|(?:all|every|each)\s+(?:\w+\s+){0,2}?(?:users?|accounts?|staff|employees|members|"
    r"mailboxes|admins?|machines|devices|clients?)|the\s+(?:whole|entire)\s+(?:tenant|company|org\w*|domain|firm))"
)
# Namespaces of the registered levers (levers/registry.json and registry.d; a test checks every one is listed) plus a
# few generic ones that attackers like to guess.
_LEVER_SPACES = (
    r"(?:user|ticket|kb|mailbox|tenant|group|device|mfa|admin|license|audit|backup|contact|inboxrule|message|"
    r"quarantine|risk|signins|restore|rag|unix|site)"
)
_LEVER_NAME = _LEVER_SPACES + r"\.[a-z]+(?:-[a-z]+)*\b(?![@.\w-])"


@dataclass(frozen=True, slots=True)
class Rule:
    """One named heuristic: an id, what it means in plain English, and the patterns that trigger it."""

    id: str
    description: str
    patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class Reason:
    """Why an input was flagged: the rule that fired and a short excerpt of the evidence."""

    rule: str
    evidence: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.evidence}"


@dataclass(frozen=True, slots=True)
class Detection:
    """Result of ``detect_injection``. ``flagged`` is true exactly when there is at least one reason."""

    flagged: bool
    reasons: tuple[Reason, ...]

    def __post_init__(self) -> None:
        if self.flagged != bool(self.reasons):
            raise ValueError("flagged must be true exactly when reasons are present")

    @property
    def rules(self) -> frozenset[str]:
        return frozenset(r.rule for r in self.reasons)


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, _FLAGS) for p in patterns)


TEXT_RULES: tuple[Rule, ...] = (
    Rule(
        "instruction-override",
        "Tells the reader to drop or replace its instructions: 'ignore previous instructions', 'you are now ...', "
        "'new instructions:', system prompt talk, developer mode, fake role tags, notes addressed to the AI.",
        _rx(
            r"\b(?:ignore|disregard|forget|override)\s+(?:(?:all|any|of|the|your|my|these|those)\s+){0,3}"
            r"(?:previous|prior|above|earlier|preceding|original|existing|system|safety|current)\s+(?:\w+\s+)?"
            r"(?:instructions?|prompts?|directives?|guidelines|guardrails|rules|context|programming)\b",
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:of\s+)?your\s+(?:\w+\s+)?"
            r"(?:instructions?|prompts?|directives?|guidelines|guardrails|rules|programming|training)\b",
            rf"\byou\s+are\s+now\s+(?:(?:a|an|the|my|in|no\s+longer)\s+)?(?:\w+\s+){{0,2}}?"
            rf"(?:{_AI}|persona|character|dan|unrestricted|unfiltered|jailbroken)\b",
            r"\b(?:new|updated|revised|real|actual|true|override|priority)\s+(?:system\s+)?instructions?\s*(?::|-|are\s*:)",
            r"\b(?:your|the\s+ai'?s?|the\s+assistant'?s?)\s+(?:system|developer|hidden|initial)\s+prompt\b",
            r"\b(?:reveal|print|repeat|show|output|ignore|override|update|replace|leak)\s+(?:the\s+|your\s+)?"
            r"(?:system|developer|hidden|initial)\s+prompt\b",
            r"\bsystem\s+prompt\s*(?::|override|update)",
            r"\b(?:developer|god|jailbreak|dan|unrestricted|sudo)\s+mode\s+(?:is\s+)?(?:now\s+)?"
            r"(?:enabled|activated|on|engaged)\b",
            r"\b(?:enter|activate|engage|switch\s+(?:in)?to|you\s+are\s+(?:now\s+)?in)\s+(?:the\s+)?"
            r"(?:developer|god|jailbreak|dan|unrestricted|sudo)\s+mode\b",
            r"<\|im_(?:start|end)\|>|\[/?INST\]|<</?SYS>>|\[(?:system|assistant|developer)(?:\s+\w+)?\]"
            r"|</?(?:system|assistant|developer)(?:_message)?>|^[ \t]*#{2,}[ \t]*(?:system|assistant|developer)\b",
            rf"\b(?:note|message|instructions?|attention|reminder)\s+(?:to|for)\s+(?:the\s+|any\s+)?(?:triage\s+)?{_AI}\b",
            rf"(?:^|[.!?>][ \t]*)(?:hey\s+|dear\s+|attention\s+)?(?:the\s+)?(?:ai\s+|triage\s+)?{_AI}\s*[,:]\s*"
            r"(?:please\s+)?(?:ignore|disregard|run|execute|call|invoke|reset|disable|grant|approve|export|send|"
            r"forward|delete|add|remove|create|close|mark|assign|reply)\b",
        ),
    ),
    Rule(
        "tool-request",
        "Asks for a lever, tool or command to be run: a lever name after call/invoke/run, 'execute the tool', "
        "'you must run the command', encoded or download-and-run PowerShell.",
        _rx(
            rf"\b(?:call|invoke|execute|trigger|run|press|pull|fire)\b[^.\n]{{0,30}}?\b{_LEVER_NAME}",
            r"\b(?:call|invoke|execute|trigger|press|pull)\s+(?:the\s+|a\s+|this\s+)?(?:[\w.-]+\s+)?(?:lever|tool)\b",
            r"\byou\s+(?:must|are\s+(?:required|instructed)\s+to|have\s+been\s+instructed\s+to)\s+"
            r"(?:now\s+|immediately\s+)?(?:call|invoke|execute|run|trigger|use)\s+(?:the\s+)?(?:following\s+)?"
            r"(?:\w+\s+)?(?:lever|tool|command|function|script)s?\b",
            r"\b(?:powershell|pwsh)(?:\.exe)?\b[^\n]{0,40}?\s-(?:e|ec|enc|encodedcommand|w\s+hidden|windowstyle\s+hidden)\b",
            r"\b(?:iex|invoke-expression)\b|\b(?:downloadstring|downloadfile)\s*\(|\b(?:curl|wget)\b[^\n|]{0,200}\|"
            r"\s*(?:ba|z)?sh\b",
        ),
    ),
    Rule(
        "safety-bypass",
        "Asks to switch off a security control (MFA, Conditional Access, audit logging, Defender) for everyone, "
        "to grant top admin rights to an outsider, or to skip the approval step.",
        _rx(
            r"\b(?:disable|turn\s+off|remove|bypass|suspend|deactivate|exempt)\b[^.\n]{0,40}?"
            r"\b(?:mfa|2fa|multi-?factor(?:\s+auth\w*)?|conditional\s+access|security\s+defaults|audit(?:\s+log\w*)?|"
            rf"logging|defender|antivirus|edr)\b[^.\n]{{0,40}}?\b(?:for|on|across|from)\s+{_ALL_TARGETS}",
            r"\b(?:mfa|2fa|multi-?factor|conditional\s+access|security\s+defaults|audit\s+log\w*)\b[^.\n]{0,30}?"
            rf"\b(?:off|disabled)\b[^.\n]{{0,30}}?\b(?:for|on|across)\s+{_ALL_TARGETS}",
            r"\b(?:skip|bypass)\s+(?:the\s+|any\s+)?(?:lead\s+|manager\s+|human\s+)?(?:approval|sign-?off|review)s?\b",
            r"\b(?:do\s+not|don'?t)\s+(?:wait|ask)\s+for\s+(?:the\s+|any\s+)?(?:lead\s+|manager\s+|human\s+)?"
            r"(?:approval|sign-?off)\b",
            r"\b(?:proceed|do\s+(?:it|this)|execute|run|act|go\s+ahead|continue)\s+(?:\w+\s+){0,3}?without\s+"
            r"(?:\w+\s+)?(?:approval|sign-?off|review|confirmation)\b",
            r"\b(?:approval|sign-?off)\s+(?:is\s+)?(?:not\s+(?:required|needed)|already\s+granted)\b",
            r"\b(?:grant|give|assign|add|make)\b[^\n]{0,40}?\b(?:global\s+admin\w*|company\s+administrator|"
            r"domain\s+admin\w*|tenant\s+admin\w*)\b[^\n]{0,60}?\b(?:external|guest|outside|personal)\b",
        ),
    ),
    Rule(
        "exfiltration",
        "Asks to send bulk data to an outside destination, or to reveal the AI's prompt, keys or secrets.",
        _rx(
            r"\b(?:send|forward|email|e-mail|export|upload|post|copy|sync|exfiltrate|dump)\b[^\n]{0,60}?"
            r"\b(?:all|every|the\s+(?:entire|whole|full))\s+(?:\w+\s+){0,2}?(?:emails?|mailbox(?:es)?|tickets?|"
            r"users?|contacts|files|documents|data|records|passwords|credentials|secrets|keys|logs|conversations)\b"
            r"[^\n]{0,60}?(?:https?://|\b(?:an?\s+)?(?:external|personal|outside)\b)",
            r"\b(?:reveal|print|output|repeat|leak|dump|display|disclose|show|list|tell\s+me)\s+(?:me\s+)?(?:all\s+)?"
            r"(?:your|the\s+(?:ai|assistant|agent|model)'?s?)\s+(?:\w+\s+)?(?:instructions|prompt|rules|"
            r"configuration|config|api\s+keys?|secrets?|credentials|tokens?|environment\s+variables|system\s+message)\b",
        ),
    ),
    Rule(
        "roleplay-jailbreak",
        "Role-play framing that asks the AI to become something without rules: 'pretend you are an unrestricted "
        "bot', 'act as if you have no restrictions', 'do anything now', 'stay in character'.",
        _rx(
            r"\b(?:pretend|imagine|suppose)\s+(?:that\s+)?(?:you(?:'re|\s+are|\s+were)|to\s+be)\s+[^.\n]{0,60}?"
            r"\b(?:ai|assistant|model|bot|dan|hacker|admin\w*|unrestricted|unfiltered|uncensored|jailbroken|evil|"
            r"no\s+(?:rules|restrictions|limits|filters))\b",
            r"\b(?:act|behave|respond|answer)\s+as\s+(?:if\s+you\s+(?:are|were|have)\s+|though\s+you\s+(?:are|were|have)\s+)?"
            r"[^.\n]{0,40}?\b(?:unrestricted|unfiltered|uncensored|jailbroken|evil|dan|no\s+(?:rules|restrictions|"
            r"limits|filters|guardrails))\b",
            r"\b(?:roleplay|role-play|role\s+play)\s+(?:as|a\s+game)\b|\bstay\s+in\s+character\b|\bdo\s+anything\s+now\b",
            r"\byou(?:'re|\s+are)?\s+(?:have\s+no|(?:now\s+)?(?:free\s+(?:of|from)|not\s+bound\s+by|no\s+longer\s+bound\s+by))"
            r"\s+(?:any\s+|all\s+|your\s+|the\s+)?(?:\w+\s+)?(?:rules|restrictions|limits|limitations|filters|"
            r"guardrails|guidelines|policies)\b",
        ),
    ),
)

STRUCTURAL_RULES: tuple[Rule, ...] = (
    Rule("invisible-characters", "Zero-width, bidi control or Unicode tag characters that hide or reorder text."),
    Rule("hidden-html-comment", "An HTML comment with words in it: invisible when rendered, read by a model."),
    Rule(
        "hidden-style",
        "Text styled to be invisible: display:none, visibility:hidden, zero or 1px font, "
        "opacity 0, or white text with no (or a white) background.",
    ),
    Rule("markdown-image-exfil", "A markdown image whose URL carries a query string: rendering it can leak data."),
    Rule("encoded-instructions", "A base64 blob that decodes to text matching the instruction rules above."),
)

RULES: tuple[Rule, ...] = STRUCTURAL_RULES[:1] + TEXT_RULES + STRUCTURAL_RULES[1:]

_HTML_COMMENT = re.compile(r"<!--(?!\s*\[(?:if|endif))(.*?)(?:-->|\Z)", re.DOTALL)
_WORD = re.compile(r"[A-Za-z]{2,}")
_HIDING_DECL = re.compile(
    r"\b(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?(?![\d.])|"
    r"font-size\s*:\s*(?:0(?:\.0+)?(?:px|pt|em|rem|%)?|(?:0?\.\d+|1)(?:px|pt))(?![\w.]))",
    re.IGNORECASE,
)
_STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(?:"([^"]{0,2000})"|'([^']{0,2000})')""", re.IGNORECASE)
_FONT_WHITE = re.compile(r"""<font\b[^>]{0,500}?\bcolor\s*=\s*["']?(?:white|#fff(?:fff)?)\b""", re.IGNORECASE)
_WHITE = frozenset({"white", "#fff", "#ffffff", "rgb(255,255,255)", "rgba(255,255,255,1)"})
_MD_IMAGE_QUERY = re.compile(
    r"!\[[^\]\n]{0,200}\]\(\s*<?(https?://[^\s)>?]{1,500}\?[^\s)>=]{0,500}=[^\s)>]{0,500})", re.IGNORECASE
)
_B64_BLOB = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{20,}={0,2}(?![A-Za-z0-9+/=_-])")


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EVIDENCE_MAX else flat[: _EVIDENCE_MAX - 3] + "..."


def _text_hits(text: str) -> Iterable[Reason]:
    for rule in TEXT_RULES:
        for pattern in rule.patterns:
            match = pattern.search(text)
            if match:
                yield Reason(rule.id, _excerpt(match.group(0)))
                break


def _white_text(style: str) -> bool:
    decls: dict[str, str] = {}
    for decl in style.split(";"):
        name, sep, value = decl.partition(":")
        if sep:
            decls[name.strip().lower()] = "".join(value.lower().replace("!important", "").split())
    if decls.get("color") not in _WHITE:
        return False
    background = decls.get("background-color", decls.get("background"))
    return background is None or background in _WHITE


def _hidden_style(text: str) -> str | None:
    match = _HIDING_DECL.search(text) or _FONT_WHITE.search(text)
    if match:
        return match.group(0)
    for attr in _STYLE_ATTR.finditer(text):
        style = attr.group(1) if attr.group(1) is not None else attr.group(2)
        if _white_text(style):
            return attr.group(0)
    return None


def _decode_base64(blob: str) -> str | None:
    """Decode a base64 or base64url blob to text, or None when it is not printable UTF-8 with words in it."""
    if len(blob) > _B64_MAX_LEN:
        return None
    standard = blob.replace("-", "+").replace("_", "/")
    try:
        decoded = base64.b64decode(standard + "=" * (-len(standard) % 4), validate=True).decode("utf-8")
    except (binascii.Error, ValueError):  # UnicodeDecodeError is a ValueError
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
    if printable < 0.95 * len(decoded) or not _WORD.search(decoded):
        return None
    return decoded


def _describe_invisible(chars: list[str]) -> str:
    distinct = sorted(set(chars))
    names = ", ".join(f"U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}" for c in distinct[:3])
    more = f" and {len(distinct) - 3} more kinds" if len(distinct) > 3 else ""
    return f"{len(chars)} hidden character(s): {names}{more}"


def detect_injection(text: str) -> Detection:
    """Scan untrusted text for prompt-injection signs and say which rules fired, with evidence."""
    found: dict[str, Reason] = {}

    def add(reason: Reason) -> None:
        found.setdefault(reason.rule, reason)

    invisible = find_invisible(text)
    if invisible:
        add(Reason("invisible-characters", _describe_invisible(invisible)))

    clean = normalise(text)
    for reason in _text_hits(clean):
        add(reason)
    variant = decoded_variant(text)  # HTML character references and look-alike letters resolved
    if variant != clean:
        for reason in _text_hits(variant):
            add(Reason(reason.rule, _excerpt(f"after resolving entities or look-alike letters: {reason.evidence}")))
    smuggled = reveal_tag_text(text)
    if smuggled:
        for reason in _text_hits(normalise(smuggled)):
            add(Reason(reason.rule, _excerpt(f"in tag characters: {reason.evidence}")))

    for comment in _HTML_COMMENT.finditer(clean):
        if len(_WORD.findall(comment.group(1))) >= 3:
            add(Reason("hidden-html-comment", _excerpt(comment.group(0))))
            break
    hidden = _hidden_style(clean)
    if hidden:
        add(Reason("hidden-style", _excerpt(hidden)))
    image = _MD_IMAGE_QUERY.search(clean)
    if image:
        add(Reason("markdown-image-exfil", _excerpt(image.group(1))))

    for blob in _B64_BLOB.findall(clean)[:_B64_MAX_BLOBS]:
        decoded = _decode_base64(blob)
        if decoded is not None and any(True for _ in _text_hits(normalise(decoded))):
            add(Reason("encoded-instructions", _excerpt(f"base64 decodes to: {decoded}")))
            break

    order = {rule.id: i for i, rule in enumerate(RULES)}
    reasons = tuple(sorted(found.values(), key=lambda r: order[r.rule]))
    return Detection(flagged=bool(reasons), reasons=reasons)
