"""Export only visible dialogue from one explicitly selected local Codex rollout.

Never exports reasoning, tool traffic, credentials, or environment/instruction
injections. This is a historical transcript, not a source of current rules.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)((?:OPENAI_API_KEY|API_SECRET|ACCESS_TOKEN|CLIENT_SECRET)\s*[=:]\s*[\"']?)[A-Za-z0-9._~+/=-]{16,}"),
)


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern in SECRET_PATTERNS:
        def replace(match):
            return (match.group(1) if match.lastindex else "") + "[REDACTED_SECRET]"
        text, found = pattern.subn(replace, text)
        count += found
    return text, count


def export(source: Path, output: Path, thread_id: str) -> dict:
    if output.exists():
        raise ValueError("fresh output directory required")
    if not source.is_file() or source.is_symlink():
        raise ValueError("regular local rollout required")
    # Fix the source boundary while the active session continues to append.
    boundary = source.stat().st_size
    source_sha = hashlib.sha256()
    counts = Counter()
    rows = []
    verified_id = None
    with source.open("rb") as stream:
        while stream.tell() < boundary:
            raw = stream.readline(boundary - stream.tell())
            source_sha.update(raw)
            if not raw.endswith(b"\n"):
                counts["incompleteTailExcluded"] += 1
                break
            event = json.loads(raw)
            payload = event.get("payload", {})
            if event.get("type") == "session_meta":
                verified_id = payload.get("id")
            if event.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                counts["systemDeveloperExcluded"] += 1
                continue
            if role == "assistant" and payload.get("channel") not in (None, "final", "commentary"):
                counts["internalAssistantExcluded"] += 1
                continue
            content = payload.get("content", [])
            text = "\n".join(part.get("text", "") for part in content
                             if isinstance(part, dict) and part.get("type") in ("input_text", "output_text", "text"))
            if not text:
                counts["nonTextMessageExcluded"] += 1
                continue
            stripped = text.lstrip()
            if role == "user" and (
                stripped.startswith(("# AGENTS.md instructions", "<environment_context>", "<permissions instructions>",
                                     "<subagent_notification>", "An MCP app initiated this message."))
                or ("<environment_context>" in text and "<cwd>" in text)
            ):
                counts["injectedContextExcluded"] += 1
                continue
            text, replaced = redact(text)
            counts["secretRedactions"] += replaced
            rows.append({"sequence": len(rows) + 1, "timestamp": event.get("timestamp"),
                         "role": role, "phase": payload.get("phase") or payload.get("channel"), "text": text})
            counts[role] += 1
    if verified_id != thread_id:
        raise ValueError("rollout thread identity mismatch")
    if not counts["user"] or not counts["assistant"]:
        raise ValueError("both visible dialogue roles required")
    output.mkdir(parents=True, exist_ok=False)
    transcript = output / "dialogue.jsonl"
    with transcript.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    result = {
        "schema": "codex_visible_dialogue_snapshot_v1", "threadId": thread_id,
        "sourceBytesAtSnapshot": boundary, "sourceSnapshotSha256": source_sha.hexdigest(),
        "firstMessageAt": rows[0]["timestamp"], "lastMessageAt": rows[-1]["timestamp"],
        "messageCount": len(rows), "counts": dict(counts),
        "dialogueBytes": transcript.stat().st_size,
        "dialogueSha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
        "scope": "visible user/assistant text only, snapshot before Git push",
        "reasoningAndToolTrafficIncluded": False,
        "historicalClaimsNotRevalidated": True, "imageAndFileAttachmentsIncluded": False,
        "sourceUnmodified": True,
    }
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output, args.thread_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
