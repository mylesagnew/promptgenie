import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from promptgenie.core.config import ScannerConfig

Risk = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


def _offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset into 1-based (line, col)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")  # rfind returns -1 if no newline → col = offset+1
    return line, col


@dataclass
class SecurityFinding:
    risk: Risk
    code: str
    message: str
    detail: str = ""
    recommendation: str = ""
    confidence: Confidence = "MEDIUM"
    line: int = 0
    col: int = 0
    matched_text: str = ""  # the text that triggered this finding (used for scoped allowlisting)


@dataclass
class ScanResult:
    findings: list[SecurityFinding] = field(default_factory=list)

    @property
    def risk_level(self) -> Risk:
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if any(f.risk == level for f in self.findings):
                return level
        return "LOW"

    def by_risk(self, risk: Risk) -> list[SecurityFinding]:
        return [f for f in self.findings if f.risk == risk]


# Secret patterns — (regex, label, confidence)
SECRET_PATTERNS = [
    (r"(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}", "API key", "MEDIUM"),
    (
        r"(secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?\S{8,}",
        "Secret/token/password",
        "MEDIUM",
    ),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI API key", "HIGH"),
    (r"AIza[A-Za-z0-9_\-]{35}", "Google API key", "HIGH"),
    (r"(xox[baprs]-[A-Za-z0-9\-]+)", "Slack token", "HIGH"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key", "HIGH"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token", "HIGH"),
    (r"AKIA[A-Z0-9]{16}", "AWS access key", "HIGH"),
    (r"(aws_secret_access_key|AWS_SECRET)\s*[:=]\s*\S{20,}", "AWS secret", "HIGH"),
]

# Prompt injection indicators — (regex, risk, code, message, confidence)
INJECTION_PATTERNS = [
    (
        r"ignore (all |previous |above |prior )?(instructions?|rules?|context|prompt)",
        "HIGH",
        "SEC_001",
        "Instruction override attempt.",
        "HIGH",
    ),
    (
        r"forget (everything|all|what you were told|your instructions)",
        "HIGH",
        "SEC_002",
        "Memory wipe instruction.",
        "HIGH",
    ),
    (
        r"(you are now|act as|pretend (you are|to be)|roleplay as)\b.{0,60}(unrestricted|without limits|no rules|jailbreak)",
        "HIGH",
        "SEC_003",
        "Roleplay jailbreak pattern.",
        "HIGH",
    ),
    (
        r"(repeat|print|output|reveal|show|display|tell me) (your|the) (system prompt|instructions|rules|context|hidden)",
        "HIGH",
        "SEC_004",
        "System prompt extraction attempt.",
        "HIGH",
    ),
    (
        r"do not (mention|say|reveal|tell|include|show) (this|that|the above|these instructions)",
        "HIGH",
        "SEC_005",
        "Output suppression instruction — hides injected behaviour.",
        "MEDIUM",
    ),
    (
        r"(translate|rephrase|summarise|summarize).{0,40}(execute|run|perform|do) (it|that|the instruction)",
        "MEDIUM",
        "SEC_006",
        "Indirect instruction execution via translation.",
        "MEDIUM",
    ),
    (
        r"(when|if) (you see|user (says|types|sends))\b.{0,80}(then|always|you must)\b",
        "MEDIUM",
        "SEC_007",
        "Conditional trigger pattern — may be a persistent injection.",
        "LOW",
    ),
]

# Agent permission risks — (regex, risk, code, message, confidence)
AGENT_PERMISSION_PATTERNS = [
    (
        r"(access|read|write|modify|delete).{0,30}(any file|all files|entire filesystem|/etc|/var|/root)",
        "CRITICAL",
        "PERM_001",
        "Unrestricted filesystem access requested.",
        "HIGH",
    ),
    (
        r"(send|make|issue|perform).{0,30}(any|all|arbitrary) (request|call|http|api)",
        "HIGH",
        "PERM_002",
        "Unrestricted network access.",
        "HIGH",
    ),
    (
        r"(run|execute|eval).{0,30}(arbitrary|any|all|user.provided) (code|command|script|shell)",
        "CRITICAL",
        "PERM_003",
        "Arbitrary code execution allowed.",
        "HIGH",
    ),
    (
        r"(access|use|call).{0,30}(email|calendar|contacts|phone|sms|messaging)",
        "HIGH",
        "PERM_004",
        "PII/communication tool access granted.",
        "MEDIUM",
    ),
    (
        r"(post|tweet|publish|send|email|message).{0,40}(without|no) (review|approval|confirmation)",
        "HIGH",
        "PERM_005",
        "Allows unsupervised external publishing.",
        "MEDIUM",
    ),
    (
        r"(install|pip install|npm install|apt install|brew install).{0,30}(any|all|whatever)",
        "HIGH",
        "PERM_006",
        "Unrestricted package installation.",
        "HIGH",
    ),
]

# RAG and data handling risks — (regex, risk, code, message, confidence)
RAG_PATTERNS = [
    (
        r"(trust|follow|execute|obey).{0,30}(instructions?|commands?).{0,30}(retrieved|fetched|found in|from the document)",
        "HIGH",
        "RAG_001",
        "Prompt instructs model to follow instructions found in retrieved content — RAG injection risk.",
        "HIGH",
    ),
    (
        r"(read|ingest|process).{0,30}(user.uploaded|user.provided|untrusted|external).{0,30}(file|document|url|webpage).{0,80}(then|and) (act|do|execute|follow)",
        "MEDIUM",
        "RAG_002",
        "Untrusted input pipeline may lead to indirect injection.",
        "MEDIUM",
    ),
]


def scan(prompt: str, config: "ScannerConfig | None" = None) -> ScanResult:
    from promptgenie.core.config import ScannerConfig as _ScannerConfig

    cfg: _ScannerConfig = config if config is not None else _ScannerConfig()
    result = ScanResult()
    lower = prompt.lower()

    # Secret detection — search original text to preserve case for patterns like AKIA/ghp_
    for pattern, label, confidence in SECRET_PATTERNS:
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            line, col = _offset_to_line_col(prompt, m.start())
            result.findings.append(
                SecurityFinding(
                    risk="CRITICAL",
                    code="SEC_SECRET",
                    message=f"Possible {label} embedded in prompt.",
                    recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
                    confidence=cast(Confidence, confidence),
                    line=line,
                    col=col,
                    matched_text=m.group(0),
                )
            )

    # Injection patterns — search lowercased text; map offset back to original
    for pattern, risk, code, msg, confidence in INJECTION_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            line, col = _offset_to_line_col(lower, m.start())
            result.findings.append(
                SecurityFinding(
                    risk=cast(Risk, risk),
                    code=code,
                    message=msg,
                    recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
                    confidence=cast(Confidence, confidence),
                    line=line,
                    col=col,
                    matched_text=m.group(0),
                )
            )

    # Agent permissions
    for pattern, risk, code, msg, confidence in AGENT_PERMISSION_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            line, col = _offset_to_line_col(lower, m.start())
            result.findings.append(
                SecurityFinding(
                    risk=cast(Risk, risk),
                    code=code,
                    message=msg,
                    recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
                    confidence=cast(Confidence, confidence),
                    line=line,
                    col=col,
                    matched_text=m.group(0),
                )
            )

    # RAG risks
    for pattern, risk, code, msg, confidence in RAG_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            line, col = _offset_to_line_col(lower, m.start())
            result.findings.append(
                SecurityFinding(
                    risk=cast(Risk, risk),
                    code=code,
                    message=msg,
                    recommendation="Treat retrieved content as data, not instructions. Summarise only; never execute.",
                    confidence=cast(Confidence, confidence),
                    line=line,
                    col=col,
                    matched_text=m.group(0),
                )
            )

    # Mixed trusted/untrusted input check — no single match offset; use line 1
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

    # Apply config: disabled rules, scoped allowlist, severity overrides.
    #
    # Allowlist entries are rule-scoped and matched-text-aware:
    #   - entry.rules non-empty → only suppresses findings with those rule codes
    #   - suppression only fires when entry.phrase appears in the finding's matched_text
    #     (not anywhere in the whole prompt — that was the original broken behaviour)
    if cfg.allowlist or cfg.disabled_rules or cfg.severity_overrides:
        filtered: list[SecurityFinding] = []
        for finding in result.findings:
            if finding.code in cfg.disabled_rules:
                continue
            if cfg.allowlist and any(
                entry.suppresses(finding.code, finding.matched_text) for entry in cfg.allowlist
            ):
                continue
            if finding.code in cfg.severity_overrides:
                finding = SecurityFinding(
                    risk=cast(Risk, cfg.severity_overrides[finding.code]),
                    code=finding.code,
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
