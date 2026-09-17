"""Mirror the session to markdown, for reading with the math rendered.

A terminal cannot render LaTeX. Inline densities and second derivatives arrive
as `g''(θ₀)` and a lesson stops being readable somewhere around the third
equation. Obsidian renders LaTeX and mermaid natively, so the fix is to write
the session into the vault and read it there.

Borrowed in shape from `amosblomqvist/learn`'s `md-log.ts`, which mirrors a
session to a markdown file for exactly this reason. Two things are taken
verbatim from it because they are load-bearing rather than incidental:

- **The question block never contains the correct answer or the rubric.** The
  answer appends only once the grading call comes back. A mirror that spoiled
  the question would be worse than no mirror.
- **Questions are written as they were displayed**, after shuffling, so what
  you re-read is what you were actually asked.

Implemented in the proxy rather than as a tool the agent calls, which is the
one real departure. The proxy already sees every frame, so the mirror costs no
tokens, cannot be forgotten in the middle of a lesson, and cannot describe the
session as something other than what happened — it *is* the transcript. And
the answer key never reaching the file stops being an instruction the agent
follows and becomes a property of the transport: this module is handed frames
that contain `correct_option_id` and `rubric`, and does not write them.

Nothing here may raise into the pump. Same rule as `trace.py`: losing the
mirror is a degraded session, crashing on it is a broken one. Every public
entry point swallows its own exceptions and records the failure in the trace.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

# Fields that carry the answer. This module reads a pose call's *output*,
# never its input, so these never come near it -- `QuizPosed` and
# `ExplainPosed` are built to be exactly "what the learner may see". They are
# named here so a test can assert the file is free of them, and so the rule is
# auditable in one place.
_WITHHELD = frozenset({
    "correct_option_id", "explanation",     # quiz
    "rubric",                               # explain
})

# The option list the teach skill is required to write: `- **A.** …`. Its
# presence just before a quiz call means the agent already posed the question
# in prose, where it is rendered in the learner's own notation. Writing the
# tool's copy underneath would show every question twice.
_POSED_IN_PROSE = re.compile(r"^\s*[-*]\s*\*\*A[.):]", re.MULTILINE)

# How much recent output to keep for that check. One exchange, not a session.
_RECENT = 3000


def default_dir() -> Path | None:
    """Where the mirror goes, or None to stay off.

    `$SMRT_MD_LOG` wins; `off` disables. Otherwise the vault's `logs/`
    directory, but only if it already exists -- the proxy should not create
    directories in someone's notes because it happened to be run with a
    different cwd.
    """
    explicit = os.environ.get("SMRT_MD_LOG")
    if explicit:
        return None if explicit.lower() == "off" else Path(explicit)
    logs = Path("/vault/logs")
    return logs if logs.is_dir() else None


class MdLog:
    """Append-only markdown mirror of one session."""

    def __init__(self, directory: Path | None, trace=None) -> None:
        self.trace = trace
        self.path: Path | None = None
        self._lock = threading.Lock()
        # Streaming text arrives in many chunks; they are joined and written
        # when the turn ends, so a paragraph is not split across appends.
        self._pending: list[str] = []
        # Tool call ids already written. `tool_call` and `tool_call_update`
        # can both carry a completed result for the same call.
        self._seen: set[str] = set()
        # Tail of what has been written, for the duplicate check above.
        self._recent = ""
        # A posed question held back to see whether the agent poses it itself.
        # Written only if nothing in the prose does, by the next user turn.
        self._deferred = ""
        if directory is None:
            return
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path = directory / f"session-{stamp}.md"
            self._append(
                f"---\ntype: session-log\nstarted: {datetime.now().isoformat(timespec='seconds')}\n---\n\n"
                f"# Session {stamp}\n\n"
                "*Written by the proxy as the session ran. The answer to a "
                "question appears only after it was answered.*\n"
            )
        except OSError as error:
            self.path = None
            self._note("md_log_unavailable", error=str(error))

    # -- writing ----------------------------------------------------------

    def _note(self, event: str, **fields: object) -> None:
        if self.trace is not None:
            try:
                self.trace.note(event, **fields)
            except Exception:       # noqa: BLE001 - never raise into the pump
                pass

    def _append(self, text: str) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def _write(self, text: str) -> None:
        """Serialized and fail-safe. Frames arrive on two pump threads."""
        if self.path is None:
            return
        try:
            with self._lock:
                self._append(text)
                self._recent = (self._recent + text)[-_RECENT:]
        except Exception as error:  # noqa: BLE001
            self._note("md_log_failed", error=str(error))

    # -- observation ------------------------------------------------------

    def observe(self, direction: str, frame: object) -> None:
        """Called for every parsed frame. Never raises."""
        if self.path is None or not isinstance(frame, dict):
            return
        try:
            self._observe(direction, frame)
        except Exception as error:  # noqa: BLE001
            self._note("md_log_failed", error=str(error))

    def _observe(self, direction: str, frame: dict) -> None:
        method = frame.get("method")
        params = frame.get("params")
        params = params if isinstance(params, dict) else {}

        if method == "session/prompt":
            self._settle()
            self._write(self._prompt_block(params))
            return

        if method != "session/update":
            # A prompt's response ends the turn, so anything still buffered
            # belongs to a message that is now complete.
            if "result" in frame:
                self._flush()
            return

        update = params.get("update")
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")

        if kind == "agent_message_chunk":
            content = update.get("content")
            if isinstance(content, dict) and content.get("type") == "text":
                self._pending.append(str(content.get("text", "")))
            return

        if kind in ("tool_call", "tool_call_update"):
            self._tool(update)

    @staticmethod
    def _payload(raw: object) -> dict | None:
        """A tool's structured result, whatever shape the adapter wrapped it in.

        Measured against `claude-agent-acp`, which sends an MCP tool's output
        as a **JSON string** rather than an object -- and `rawInput` as null.
        The first version of this module required a dict, so it matched
        nothing and silently wrote no questions and no grades at all for a
        whole session. `compat.py` has already recorded lists arriving here
        too, so both are handled.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            # MCP content blocks: [{"type": "text", "text": "{...}"}]
            for block in raw:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    found = MdLog._payload(block["text"])
                    if found is not None:
                        return found
            return None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                return None
            return parsed if isinstance(parsed, dict) else None
        return None

    def _tool(self, update: dict) -> None:
        """Write from the tool's OUTPUT, never its input.

        The input to `quiz` carries `correct_option_id` and `explanation`, and
        its options are in the order the agent authored them, before shuffling.
        The output is `QuizPosed`, which is built to be precisely what the
        learner may see and is the order they saw it in. So reading the output
        is both safer and more accurate, and this module never has to strip
        anything -- it simply never holds the key.
        """
        # Any tool call ends the message that preceded it, whether or not it
        # is one worth mirroring. Without this, two agent messages either side
        # of a `Read` are written as one run-on paragraph.
        #
        # `_settle` rather than `_flush`, so a held question is written before
        # whatever this call produces. Otherwise a grade could reach the log
        # ahead of the question it grades.
        self._settle()
        if update.get("status") != "completed":
            return
        call_id = str(update.get("toolCallId") or "")
        if call_id and call_id in self._seen:
            return
        out = self._payload(update.get("rawOutput"))
        if out is None:
            return

        block = ""
        if "options" in out and "question_id" in out:
            # Only as a fallback, and DEFERRED rather than written here.
            #
            # If the agent poses the question properly in prose, that version
            # is the one the learner read, with the maths typeset. Checking
            # `_recent` alone only catches the case where the prose came
            # first. Measured 2026-09-15: the tool call came first, the check
            # found nothing to dedupe against, and the log carried the same
            # question twice -- once in tool spelling, once in the agent's.
            #
            # So hold it. `_flush` drops it if the prose turns out to pose the
            # question, and the next user turn writes it if nothing did.
            if call_id:
                self._seen.add(call_id)
            if not _POSED_IN_PROSE.search(self._recent):
                self._deferred = self._quiz_block(out)
            return
        elif "rubric_items" in out and "question" in out:
            block = self._explain_block(out)
        elif "diagnosis" in out:
            block = self._quiz_result(out)
        elif "hit" in out and "missed" in out:
            block = self._explain_result(out)
        if not block:
            return

        if call_id:
            self._seen.add(call_id)
        self._flush()
        self._write(block)

    def _flush(self) -> None:
        if not self._pending:
            return
        text = "".join(self._pending).strip()
        self._pending.clear()
        if text:
            if self._deferred and _POSED_IN_PROSE.search(text):
                # The agent posed it itself. Its version wins.
                self._deferred = ""
            self._write(f"\n{text}\n")

    def _settle(self) -> None:
        """Write a held question that the prose never got around to posing."""
        self._flush()
        if self._deferred:
            self._write(self._deferred)
            self._deferred = ""

    def close(self) -> None:
        try:
            self._settle()
            self._write(f"\n---\n\n*Session ended "
                        f"{datetime.now().isoformat(timespec='seconds')}.*\n")
        except Exception:       # noqa: BLE001
            pass

    # -- blocks -----------------------------------------------------------

    @staticmethod
    def _prompt_block(params: dict) -> str:
        blocks = params.get("prompt")
        said = []
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    said.append(str(block.get("text", "")))
        body = "\n".join(said).strip()
        return f"\n## You\n\n{body}\n" if body else ""

    @staticmethod
    def _quiz_block(out: dict) -> str:
        """The question as the learner saw it: shuffled order, A-D labels."""
        lines = ["\n### Quiz\n", f"\n{out.get('prompt', '')}\n\n"]
        options = out.get("options")
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    lines.append(f"- **{option.get('id')}.** "
                                 f"{option.get('text', '')}\n")
        if hint := out.get("hint"):
            lines.append(f"\n*Hint: {hint}*\n")
        return "".join(lines)

    @staticmethod
    def _explain_block(out: dict) -> str:
        """Only what the prose will not have said.

        The question itself is posed in the conversation -- a tool call cannot
        ask anyone anything -- so restating it here would duplicate it. What
        the prose has no reason to carry is the shape of the commitment: how
        many rubric items were fixed before the question was shown, and which
        vocabulary is already being counted against.
        """
        lines = ["\n*"]
        count = out.get("rubric_items")
        if count:
            # The number of rubric items, never the items. Knowing there are
            # three things to cover is part of the question; knowing what they
            # are is the answer.
            lines.append(f"Rubric committed: {count} items.")
        vocab = out.get("vocabulary")
        if isinstance(vocab, list) and vocab:
            named = ", ".join(
                f"`{v.get('name')}` ({v.get('tier')})"
                for v in vocab if isinstance(v, dict)
            )
            lines.append(f" Vocabulary: {named}.")
        if len(lines) == 1:
            return ""
        lines.append("*\n")
        return "".join(lines)

    @staticmethod
    def _quiz_result(out: dict) -> str:
        """Folded shut, because the agent says all of this better.

        The tool's `explanation` was committed before the question was shown
        and the agent's own account of the grade follows in prose, tailored to
        what the learner actually said. Printing both leaves the log saying
        everything twice, in two registers.

        The record still matters -- it is the pre-commitment, and checking the
        prose against it is the point -- so it is kept and collapsed rather
        than dropped. The diagnosis stays in the summary line, visible while
        folded, because that is the one word worth skimming for.
        """
        # `pick_state`, not `pick_correct`. The boolean is False for "I don't
        # know" as well as for a wrong answer, and rendering that as "pick
        # wrong" told a learner who had honestly declined to guess that they
        # had got it wrong -- in the log, under the grade. Declining is the
        # behaviour the "I don't know" option exists to encourage; scoring it
        # as an error is the one reading guaranteed to stop it.
        mark = {"right": "correct", "wrong": "wrong",
                "unknown": "declined"}.get(str(out.get("pick_state") or ""))
        if mark is None:      # older payloads carry only the boolean
            mark = "correct" if out.get("pick_correct") else "wrong"
        head = f"{out.get('diagnosis')} — pick {mark}"
        if verdict := out.get("reason_verdict"):
            head += f", reasoning {verdict}"
        body = [f"\n<details><summary><b>Graded:</b> {head}</summary>\n\n"]
        for key in ("explanation", "next_step"):
            # Released by the grading call, so no longer a secret. This is the
            # only place either appears, and it is after the answer.
            if value := out.get(key):
                body.append(f"{value}\n\n")
        body.append("</details>\n")
        return "".join(body)

    @staticmethod
    def _explain_result(out: dict) -> str:
        verdict = "passed" if out.get("passed") else "not yet"
        lines = ["\n#### Graded\n", f"\n**{verdict}**\n"]
        for item in out.get("hit") or []:
            lines.append(f"\n- ✓ {item}")
        for item in out.get("missed") or []:
            lines.append(f"\n- ✗ {item}")
        lines.append("\n")
        rubric = out.get("rubric")
        if isinstance(rubric, list) and rubric:
            # In plaintext only now. `rubric_sha256` was committed before the
            # question was shown, so this can be checked against it.
            lines.append("\n<details><summary>Rubric, as committed"
                         "</summary>\n\n")
            for item in rubric:
                lines.append(f"- {item}\n")
            lines.append("\n</details>\n")
        if comment := out.get("comment"):
            lines.append(f"\n{comment}\n")
        return "".join(lines)


def withheld(raw: object) -> list[str]:
    """Which answer-carrying fields were present. For the trace, and for a
    test that asserts none of them reached the file."""
    if not isinstance(raw, dict):
        return []
    return sorted(_WITHHELD & set(raw))


# An option id is a letter or two. Searching a document for "a" proves
# nothing, and the id is not the leak in any case -- options are relabelled by
# position, so the authored id names nothing the learner can see. What would
# actually spoil a question is the prose: the explanation, or a rubric item.
_MEANINGFUL = 12


def contains_key(text: str, raw: object) -> bool:
    """True if any withheld value long enough to be a giveaway is in `text`."""
    if not isinstance(raw, dict):
        return False
    for name in _WITHHELD:
        value = raw.get(name)
        for candidate in (value if isinstance(value, list) else [value]):
            if not isinstance(candidate, str) or len(candidate) < _MEANINGFUL:
                continue
            if candidate in text:
                return True
    return False
