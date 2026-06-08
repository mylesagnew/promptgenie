import base64
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from promptgenie.core.config import ScannerConfig

FindingRisk = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ScanRisk = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]
Risk = FindingRisk  # backwards-compat alias used by callers
Confidence = Literal["HIGH", "MEDIUM", "LOW"]

# Maximum findings emitted per rule per scan (prevents finding-flood on adversarial input).
MAX_FINDINGS_PER_RULE: int = 5


def _offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset into 1-based (line, col)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")  # rfind returns -1 if no newline → col = offset+1
    return line, col


@dataclass
class SecurityFinding:
    risk: FindingRisk
    code: str
    message: str
    detail: str = ""
    recommendation: str = ""
    confidence: Confidence = "MEDIUM"
    line: int = 0
    col: int = 0
    matched_text: str = ""  # the text that triggered this finding (used for scoped allowlisting)
    category: str = ""  # rule category: secret | injection | permission | rag | obfuscation
    source: str = "builtin"  # "builtin" | "registry" | "custom"


@dataclass
class ScanResult:
    findings: list[SecurityFinding] = field(default_factory=list)

    @property
    def risk_level(self) -> ScanRisk:
        """Highest risk across all findings, or ``"NONE"`` when there are none."""
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if any(f.risk == level for f in self.findings):
                return level
        return "NONE"

    def by_risk(self, risk: Risk) -> list[SecurityFinding]:
        return [f for f in self.findings if f.risk == risk]


@dataclass
class ScanRule:
    """A single scanner rule entry.

    Fields:
        id               Stable rule code used in allowlists and severity overrides (e.g. SEC_001).
        category         Logical grouping: secret | injection | permission | rag | obfuscation.
        pattern          Python regex pattern string.
        risk             Default severity: CRITICAL | HIGH | MEDIUM | LOW.
        confidence       Detector confidence: HIGH | MEDIUM | LOW.
        message          Short human-readable finding description.
        recommendation   Actionable remediation guidance.
        false_positive_note  Common false-positive scenarios to help reviewers triage.
        use_original_text    Search original prompt text instead of NFKC-normalised lowercase.
                             Set True for case-sensitive patterns (AWS keys, GitHub tokens, etc.).
        flags            Extra re flags passed to re.search (e.g. re.DOTALL for multiline rules).
    """

    id: str
    category: str
    pattern: str
    risk: Risk
    confidence: Confidence
    message: str
    recommendation: str
    false_positive_note: str = ""
    use_original_text: bool = False
    flags: int = 0


# ── Built-in rule registry ────────────────────────────────────────────────────

# Backwards-compat alias set: ``SEC_SECRET`` in ``disabled_rules`` or ``enabled_rules``
# now matches all secret sub-rules.  Individual sub-rules can also be targeted directly.
SEC_SECRET_CODES: frozenset[str] = frozenset(
    {
        "SEC_SECRET",  # wildcard alias
        "SEC_SECRET_APIKEY",
        "SEC_SECRET_TOKEN",
        "SEC_SECRET_OPENAI",
        "SEC_SECRET_GOOGLE",
        "SEC_SECRET_SLACK",
        "SEC_SECRET_PRIVKEY",
        "SEC_SECRET_GITHUB",
        "SEC_SECRET_AWS_KEY",
        "SEC_SECRET_AWS_SECRET",
    }
)

SCAN_RULES: list[ScanRule] = [
    # ── Secret detection (case-sensitive, original text) ─────────────────────
    ScanRule(
        id="SEC_SECRET_APIKEY",
        category="secret",
        pattern=r"(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
        risk="CRITICAL",
        confidence="MEDIUM",
        message="Possible API key embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        false_positive_note="May trigger on example or placeholder tokens in documentation.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_TOKEN",
        category="secret",
        pattern=r"(secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?\S{8,}",
        risk="CRITICAL",
        confidence="MEDIUM",
        message="Possible secret/token/password embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        false_positive_note="May trigger on example values like 'password=changeme'.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_OPENAI",
        category="secret",
        pattern=r"sk-[A-Za-z0-9]{20,}",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible OpenAI API key embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_GOOGLE",
        category="secret",
        pattern=r"AIza[A-Za-z0-9_\-]{35}",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible Google API key embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_SLACK",
        category="secret",
        pattern=r"(xox[baprs]-[A-Za-z0-9\-]+)",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible Slack token embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_PRIVKEY",
        category="secret",
        pattern=r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible private key embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_GITHUB",
        category="secret",
        pattern=r"ghp_[A-Za-z0-9]{36}",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible GitHub personal access token embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_AWS_KEY",
        category="secret",
        pattern=r"AKIA[A-Z0-9]{16}",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible AWS access key embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    ScanRule(
        id="SEC_SECRET_AWS_SECRET",
        category="secret",
        pattern=r"(aws_secret_access_key|AWS_SECRET)\s*[:=]\s*\S{20,}",
        risk="CRITICAL",
        confidence="HIGH",
        message="Possible AWS secret embedded in prompt.",
        recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
        use_original_text=True,
    ),
    # Prompt injection
    ScanRule(
        id="SEC_001",
        category="injection",
        pattern=r"ignore (all |previous |above |prior )?(instructions?|rules?|context|prompt)",
        risk="HIGH",
        confidence="HIGH",
        message="Instruction override attempt.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        false_positive_note="May trigger on security documentation that describes this attack pattern.",
    ),
    ScanRule(
        id="SEC_002",
        category="injection",
        pattern=r"forget (everything|all|what you were told|your instructions)",
        risk="HIGH",
        confidence="HIGH",
        message="Memory wipe instruction.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
    ),
    ScanRule(
        id="SEC_003",
        category="injection",
        pattern=r"(you are now|act as|pretend (you are|to be)|roleplay as)\b.{0,60}(unrestricted|without limits|no rules|jailbreak)",
        risk="HIGH",
        confidence="HIGH",
        message="Roleplay jailbreak pattern.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
    ),
    ScanRule(
        id="SEC_004",
        category="injection",
        pattern=r"(repeat|print|output|reveal|show|display|tell me) (your|the) (system prompt|instructions|rules|context|hidden)",
        risk="HIGH",
        confidence="HIGH",
        message="System prompt extraction attempt.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
    ),
    ScanRule(
        id="SEC_005",
        category="injection",
        pattern=r"do not (mention|say|reveal|tell|include|show) (this|that|the above|these instructions)",
        risk="HIGH",
        confidence="MEDIUM",
        message="Output suppression instruction — hides injected behaviour.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
    ),
    ScanRule(
        id="SEC_006",
        category="injection",
        pattern=r"(translate|rephrase|summarise|summarize).{0,40}(execute|run|perform|do) (it|that|the instruction)",
        risk="MEDIUM",
        confidence="MEDIUM",
        message="Indirect instruction execution via translation.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
    ),
    ScanRule(
        id="SEC_007",
        category="injection",
        pattern=r"(when|if) (you see|user (says|types|sends))\b.{0,80}(then|always|you must)\b",
        risk="MEDIUM",
        confidence="LOW",
        message="Conditional trigger pattern — may be a persistent injection.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        false_positive_note="Commonly triggers on legitimate conditional instructions in structured prompts.",
    ),
    # Agent permission risks
    ScanRule(
        id="PERM_001",
        category="permission",
        pattern=r"(access|read|write|modify|delete).{0,30}(any file|all files|entire filesystem|/etc|/var|/root)",
        risk="CRITICAL",
        confidence="HIGH",
        message="Unrestricted filesystem access requested.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    ScanRule(
        id="PERM_002",
        category="permission",
        pattern=r"(send|make|issue|perform).{0,30}(any|all|arbitrary) (request|call|http|api)",
        risk="HIGH",
        confidence="HIGH",
        message="Unrestricted network access.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    ScanRule(
        id="PERM_003",
        category="permission",
        pattern=r"(run|execute|eval).{0,30}(arbitrary|any|all|user.provided) (code|command|script|shell)",
        risk="CRITICAL",
        confidence="HIGH",
        message="Arbitrary code execution allowed.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    ScanRule(
        id="PERM_004",
        category="permission",
        pattern=r"(access|use|call).{0,30}(email|calendar|contacts|phone|sms|messaging)",
        risk="HIGH",
        confidence="MEDIUM",
        message="PII/communication tool access granted.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    ScanRule(
        id="PERM_005",
        category="permission",
        pattern=r"(post|tweet|publish|send|email|message).{0,40}(without|no) (review|approval|confirmation)",
        risk="HIGH",
        confidence="MEDIUM",
        message="Allows unsupervised external publishing.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    ScanRule(
        id="PERM_006",
        category="permission",
        pattern=r"(install|pip install|npm install|apt install|brew install).{0,30}(any|all|whatever)",
        risk="HIGH",
        confidence="HIGH",
        message="Unrestricted package installation.",
        recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
    ),
    # RAG and data handling risks
    ScanRule(
        id="RAG_001",
        category="rag",
        pattern=r"(trust|follow|execute|obey).{0,30}(instructions?|commands?).{0,30}(retrieved|fetched|found in|from the document)",
        risk="HIGH",
        confidence="HIGH",
        message="Prompt instructs model to follow instructions found in retrieved content — RAG injection risk.",
        recommendation="Treat retrieved content as data, not instructions. Summarise only; never execute.",
    ),
    ScanRule(
        id="RAG_002",
        category="rag",
        pattern=r"(read|ingest|process).{0,30}(user.uploaded|user.provided|untrusted|external).{0,30}(file|document|url|webpage).{0,80}(then|and) (act|do|execute|follow)",
        risk="MEDIUM",
        confidence="MEDIUM",
        message="Untrusted input pipeline may lead to indirect injection.",
        recommendation="Treat retrieved content as data, not instructions. Summarise only; never execute.",
    ),
    # Multiline / split-token override patterns (DOTALL)
    ScanRule(
        id="SEC_SPLIT_001",
        category="obfuscation",
        pattern=r"ignore\s*\n+\s*(all\s+)?(previous|prior|above)?\s*\n*\s*(instructions?|rules?|context)",
        risk="HIGH",
        confidence="MEDIUM",
        message="Split-line instruction override attempt.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        flags=re.DOTALL,
    ),
    ScanRule(
        id="SEC_SPLIT_002",
        category="obfuscation",
        pattern=r"(system\s+prompt|your\s+instructions?)\s*\n+.*\s*(ignore|discard|forget|override)",
        risk="HIGH",
        confidence="MEDIUM",
        message="Multiline system-prompt override attempt.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        flags=re.DOTALL,
    ),
    ScanRule(
        id="SEC_SPLIT_003",
        category="obfuscation",
        pattern=r"<!--.*?(ignore|override|forget|jailbreak).*?-->",
        risk="HIGH",
        confidence="MEDIUM",
        message="HTML comment used to smuggle override instruction.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        flags=re.DOTALL,
    ),
    ScanRule(
        id="SEC_SPLIT_004",
        category="obfuscation",
        pattern=r"/\*.*?(ignore|override|forget|jailbreak).*?\*/",
        risk="HIGH",
        confidence="MEDIUM",
        message="Block comment used to smuggle override instruction.",
        recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
        flags=re.DOTALL,
    ),
]

# Base64 / encoding detection constants.
# A base64 blob inside a prompt is unusual. Short blobs (≤40 chars) are common
# false-positives (UUIDs, short tokens), so we only flag longer ones.
_BASE64_CHARS = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_BASE64_MIN_LENGTH = 40


def _looks_like_base64(blob: str) -> bool:
    """Return True if *blob* is likely a base64-encoded payload."""
    if len(blob) < _BASE64_MIN_LENGTH:
        return False
    # Must be valid base64 length (multiple of 4 after padding normalisation)
    padded = blob + "=" * (-len(blob) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
    except Exception:
        return False
    # Only flag if decoded bytes look like printable ASCII / control characters —
    # pure binary (many non-printable bytes) is probably a false positive.
    printable = sum(32 <= b < 127 for b in decoded)
    return printable / len(decoded) > 0.7


def _normalize(text: str) -> str:
    """NFKC-normalize *text* and lowercase for matching.

    NFKC converts look-alike Unicode characters (homoglyphs, fullwidth letters,
    compatibility forms) to their canonical ASCII equivalents before regex rules
    are applied, closing the most common Unicode-obfuscation evasion path.
    """
    return unicodedata.normalize("NFKC", text).lower()


def scan(prompt: str, config: "ScannerConfig | None" = None) -> ScanResult:
    from promptgenie.core.config import ScannerConfig as _ScannerConfig

    cfg: _ScannerConfig = config if config is not None else _ScannerConfig()
    result = ScanResult()
    # NFKC-normalize + lowercase: closes Unicode homoglyph / fullwidth evasion.
    lower = _normalize(prompt)

    # Load rules from rules_dirs (registry packs and custom rule dirs)
    dir_rules: list[ScanRule] = []
    if cfg.rules_dirs:
        from promptgenie.core.registry import load_scan_rules_from_dirs

        dir_rules = load_scan_rules_from_dirs(cfg.rules_dirs)

    active_rules = SCAN_RULES + dir_rules + list(cfg.custom_scan_rules)

    for rule in active_rules:
        search_text = prompt if rule.use_original_text else lower
        flags = re.IGNORECASE | rule.flags if rule.use_original_text else rule.flags
        for _count, m in enumerate(re.finditer(rule.pattern, search_text, flags)):
            if _count >= MAX_FINDINGS_PER_RULE:
                break
            line, col = _offset_to_line_col(search_text, m.start())
            matched = m.group(0)
            # Truncate long matches from multiline rules
            display_match = matched[:120] + ("…" if len(matched) > 120 else "")
            result.findings.append(
                SecurityFinding(
                    risk=rule.risk,
                    code=rule.id,
                    category=rule.category,
                    message=rule.message,
                    recommendation=rule.recommendation,
                    confidence=rule.confidence,
                    line=line,
                    col=col,
                    matched_text=display_match,
                )
            )

    # Base64 blob detection — flag long base64 strings that decode to readable text.
    # Not expressible as a simple regex rule; kept as special logic.
    for m in _BASE64_CHARS.finditer(prompt):
        blob = m.group(0)
        if _looks_like_base64(blob):
            line, col = _offset_to_line_col(prompt, m.start())
            result.findings.append(
                SecurityFinding(
                    risk="MEDIUM",
                    code="SEC_B64",
                    message="Base64-encoded payload detected — possible obfuscated instruction.",
                    recommendation="Decode and inspect embedded base64 blobs before processing. Reject unexplained encoded content in prompts.",
                    confidence="MEDIUM",
                    line=line,
                    col=col,
                    matched_text=blob[:80] + ("…" if len(blob) > 80 else ""),
                )
            )

    # Mixed trusted/untrusted input check — no single match offset; use line 1.
    # Requires two independent keyword classes; not expressible as a single regex rule.
    has_web_read = any(
        w in lower for w in ["fetch", "read url", "browse", "web search", "retrieve from"]
    )
    has_action = any(
        w in lower for w in ["send email", "post to", "write to file", "execute", "deploy"]
    )
    if has_web_read and has_action:
        result.findings.append(
            SecurityFinding(
                risk="HIGH",
                code="SEC_CHAIN",
                message="Prompt chains web content retrieval with an action (email, deploy, write). Classic confused-deputy / SSRF-by-proxy pattern.",
                recommendation="Treat web content as untrusted. Do not follow instructions in retrieved content. Require human approval before any action.",
                confidence="MEDIUM",
                line=1,
                col=1,
                matched_text="",
            )
        )

    # Apply config: enabled_rules whitelist (post-special-logic filter).
    # "SEC_SECRET" in enabled_rules matches all SEC_SECRET_* sub-rule codes via the alias set.
    if cfg.enabled_rules:
        enabled_set = set(cfg.enabled_rules)
        # Expand "SEC_SECRET" alias so users don't need to list all sub-codes.
        if "SEC_SECRET" in enabled_set:
            enabled_set.update(SEC_SECRET_CODES)
        result.findings = [f for f in result.findings if f.code in enabled_set]

    # Apply config: disabled rules, scoped allowlist, severity overrides.
    #
    # Allowlist entries are rule-scoped and matched-text-aware:
    #   - entry.rules non-empty → only suppresses findings with those rule codes
    #   - suppression only fires when entry.phrase appears in the finding's matched_text
    #     (not anywhere in the whole prompt — that was the original broken behaviour)
    if cfg.allowlist or cfg.disabled_rules or cfg.severity_overrides:
        # Expand "SEC_SECRET" alias in disabled_rules too.
        disabled_set = set(cfg.disabled_rules)
        if "SEC_SECRET" in disabled_set:
            disabled_set.update(SEC_SECRET_CODES)

        filtered: list[SecurityFinding] = []
        for finding in result.findings:
            if finding.code in disabled_set:
                continue
            if cfg.allowlist and any(
                entry.suppresses(finding.code, finding.matched_text) for entry in cfg.allowlist
            ):
                continue
            if finding.code in cfg.severity_overrides:
                finding = SecurityFinding(
                    risk=cast(FindingRisk, cfg.severity_overrides[finding.code]),
                    code=finding.code,
                    category=finding.category,
                    source=finding.source,
                    message=finding.message,
                    detail=finding.detail,
                    recommendation=finding.recommendation,
                    confidence=finding.confidence,
                    line=finding.line,
                    col=finding.col,
                    matched_text=finding.matched_text,
                )
            filtered.append(finding)
        result.findings = filtered

    return result
