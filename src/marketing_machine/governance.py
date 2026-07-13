from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .schemas import ContentBrief


class PolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"


@dataclass
class GovernanceDecision:
    action: PolicyAction
    reason: str


@dataclass
class GovernancePolicy:
    name: str
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    require_human_approval: list[str] = field(default_factory=list)
    max_calls_per_request: int = 25
    content_rules: dict[str, Any] = field(default_factory=dict)
    governance_level: str = "strict"

    @classmethod
    def from_json_file(cls, path: str | Path) -> "GovernancePolicy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=data["name"],
            allowed_tools=data.get("allowed_tools", []),
            blocked_tools=data.get("blocked_tools", []),
            blocked_patterns=data.get("blocked_patterns", []),
            require_human_approval=data.get("require_human_approval", []),
            max_calls_per_request=data.get("max_calls_per_request", 25),
            content_rules=data.get("content_rules", {}),
            governance_level=data.get("governance_level", "strict"),
        )

    def check_tool(self, tool_name: str) -> GovernanceDecision:
        if tool_name in self.blocked_tools:
            return GovernanceDecision(PolicyAction.DENY, f"tool '{tool_name}' is blocked")
        if tool_name in self.require_human_approval:
            return GovernanceDecision(PolicyAction.REVIEW, f"tool '{tool_name}' requires human approval")
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return GovernanceDecision(PolicyAction.DENY, f"tool '{tool_name}' is not allowlisted")
        return GovernanceDecision(PolicyAction.ALLOW, "allowed")

    def check_content(self, text: str) -> GovernanceDecision:
        for pattern in self.blocked_patterns:
            if re.search(pattern, text or "", re.IGNORECASE):
                return GovernanceDecision(
                    PolicyAction.DENY,
                    "content safety policy requires a new draft",
                )
        return GovernanceDecision(PolicyAction.ALLOW, "allowed")

    def check_brief(self, brief: ContentBrief) -> GovernanceDecision:
        errors = brief.validate()
        if errors:
            return GovernanceDecision(PolicyAction.DENY, "; ".join(errors))
        if self.content_rules.get("human_approval_required_before_publish", True):
            return GovernanceDecision(PolicyAction.REVIEW, "human approval required before scheduling or publishing")
        return GovernanceDecision(PolicyAction.ALLOW, "allowed")


@dataclass
class AuditEntry:
    agent_id: str
    tool_name: str
    action: str
    policy_name: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class AuditTrail:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def log(self, agent_id: str, tool_name: str, action: str, policy_name: str, **details: Any) -> None:
        self.entries.append(
            AuditEntry(
                agent_id=agent_id,
                tool_name=tool_name,
                action=action,
                policy_name=policy_name,
                details=details,
            )
        )

    def denied(self) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.action == PolicyAction.DENY.value]

    def to_jsonl(self) -> str:
        lines = []
        for entry in self.entries:
            lines.append(
                json.dumps(
                    {
                        "timestamp": entry.timestamp,
                        "agent_id": entry.agent_id,
                        "tool_name": entry.tool_name,
                        "action": entry.action,
                        "policy_name": entry.policy_name,
                        **entry.details,
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines)
