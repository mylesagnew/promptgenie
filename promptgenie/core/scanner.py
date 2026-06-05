import re
from dataclasses import dataclass, field
from typing import Literal

Risk = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


@dataclass
class SecurityFinding:
    risk: Risk
    code: str
    message: str
    detail: str = ""
    recommendation: str = ""


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


# Secret patterns
SECRET_PATTERNS = [
    (r"(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}", "API key"),
    (r"(secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?\S{8,}", "Secret/token/password"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI API key"),
    (r"AIza[A-Za-z0-9_\-]{35}", "Google API key"),
    (r"(xox[baprs]-[A-Za-z0-9\-]+)", "Slack token"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"AKIA[A-Z0-9]{16}", "AWS access key"),
    (r"(aws_secret_access_key|AWS_SECRET)\s*[:=]\s*\S{20,}", "AWS secret"),
]

# Prompt injection indicators
INJECTION_PATTERNS = [
    (r"ignore (all |previous |above |prior )?(instructions?|rules?|context|prompt)", "HIGH", "SEC_001",
     "Instruction override attempt."),
    (r"forget (everything|all|what you were told|your instructions)", "HIGH", "SEC_002",
     "Memory wipe instruction."),
    (r"(you are now|act as|pretend (you are|to be)|roleplay as)\b.{0,60}(unrestricted|without limits|no rules|jailbreak)",
     "HIGH", "SEC_003", "Roleplay jailbreak pattern."),
    (r"(repeat|print|output|reveal|show|display|tell me) (your|the) (system prompt|instructions|rules|context|hidden)",
     "HIGH", "SEC_004", "System prompt extraction attempt."),
    (r"do not (mention|say|reveal|tell|include|show) (this|that|the above|these instructions)", "HIGH", "SEC_005",
     "Output suppression instruction — hides injected behaviour."),
    (r"(translate|rephrase|summarise|summarize).{0,40}(execute|run|perform|do) (it|that|the instruction)",
     "MEDIUM", "SEC_006", "Indirect instruction execution via translation."),
    (r"(when|if) (you see|user (says|types|sends))\b.{0,80}(then|always|you must)\b", "MEDIUM", "SEC_007",
     "Conditional trigger pattern — may be a persistent injection."),
]

# Agent permission risks
AGENT_PERMISSION_PATTERNS = [
    (r"(access|read|write|modify|delete).{0,30}(any file|all files|entire filesystem|/etc|/var|/root)",
     "CRITICAL", "PERM_001", "Unrestricted filesystem access requested."),
    (r"(send|make|issue|perform).{0,30}(any|all|arbitrary) (request|call|http|api)", "HIGH", "PERM_002",
     "Unrestricted network access."),
    (r"(run|execute|eval).{0,30}(arbitrary|any|all|user.provided) (code|command|script|shell)", "CRITICAL",
     "PERM_003", "Arbitrary code execution allowed."),
    (r"(access|use|call).{0,30}(email|calendar|contacts|phone|sms|messaging)", "HIGH", "PERM_004",
     "PII/communication tool access granted."),
    (r"(post|tweet|publish|send|email|message).{0,40}(without|no) (review|approval|confirmation)", "HIGH",
     "PERM_005", "Allows unsupervised external publishing."),
    (r"(install|pip install|npm install|apt install|brew install).{0,30}(any|all|whatever)", "HIGH",
     "PERM_006", "Unrestricted package installation."),
]

# RAG and data handling risks
RAG_PATTERNS = [
    (r"(trust|follow|execute|obey).{0,30}(instructions?|commands?).{0,30}(retrieved|fetched|found in|from the document)",
     "HIGH", "RAG_001", "Prompt instructs model to follow instructions found in retrieved content — RAG injection risk."),
    (r"(read|ingest|process).{0,30}(user.uploaded|user.provided|untrusted|external).{0,30}(file|document|url|webpage).{0,80}(then|and) (act|do|execute|follow)",
     "MEDIUM", "RAG_002", "Untrusted input pipeline may lead to indirect injection."),
]


def scan(prompt: str) -> ScanResult:
    result = ScanResult()
    lower = prompt.lower()

    # Secret detection
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            result.findings.append(SecurityFinding(
                risk="CRITICAL",
                code="SEC_SECRET",
                message=f"Possible {label} embedded in prompt.",
                recommendation="Remove secrets from prompts. Use environment variables or secret references instead.",
            ))

    # Injection patterns
    for pattern, risk, code, msg in INJECTION_PATTERNS:
        if re.search(pattern, lower):
            result.findings.append(SecurityFinding(
                risk=risk,
                code=code,
                message=msg,
                recommendation="Treat this content as untrusted. Do not follow instructions embedded in retrieved or user-supplied data.",
            ))

    # Agent permissions
    for pattern, risk, code, msg in AGENT_PERMISSION_PATTERNS:
        if re.search(pattern, lower):
            result.findings.append(SecurityFinding(
                risk=risk,
                code=code,
                message=msg,
                recommendation="Restrict agent permissions to minimum required scope. Add explicit approval gates.",
            ))

    # RAG risks
    for pattern, risk, code, msg in RAG_PATTERNS:
        if re.search(pattern, lower):
            result.findings.append(SecurityFinding(
                risk=risk,
                code=code,
                message=msg,
                recommendation="Treat retrieved content as data, not instructions. Summarise only; never execute.",
            ))

    # Mixed trusted/untrusted input check
    has_web_read = any(w in lower for w in ["fetch", "read url", "browse", "web search", "retrieve from"])
    has_action = any(w in lower for w in ["send email", "post to", "write to file", "execute", "deploy"])
    if has_web_read and has_action:
        result.findings.append(SecurityFinding(
            risk="HIGH",
            code="SEC_CHAIN",
            message="Prompt chains web content retrieval with an action (email, deploy, write). Classic confused-deputy / SSRF-by-proxy pattern.",
            recommendation="Treat web content as untrusted. Do not follow instructions in retrieved content. Require human approval before any action.",
        ))

    return result
