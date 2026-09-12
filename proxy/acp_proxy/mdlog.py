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

import os
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
            self._flush()
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

    def _tool(self, update: dict) -> None:
        """Write from the tool's OUTPUT, never its input.

        The input to `quiz` carries `correct_option_id` and `explanation`, and
        its options are in the order the agent authored them, before shuffling.
        The output is `QuizPosed`, which is built to be precisely what the
        learner may see and is the order they saw it in. So reading the output
        is both safer and more accurate, and this module never has to strip
        anything -- it simply never holds the key.
        """
        if update.get("status") != "completed":
            return
        call_id = str(update.get("toolCallId") or "")
        if call_id and call_id in self._seen:
            return
        out = update.get("rawOutput")
        if not isinstance(out, dict):
            return

        block = ""
        if "options" in out and "question_id" in out:
            block = self._quiz_block(out)
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
            self._write(f"\n{text}\n")

    def close(self) -> None:
        try:
            self._flush()
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
        lines = ["\n### Explain\n", f"\n{out.get('question', '')}\n"]
        count = out.get("rubric_items")
        if count:
            # The number of rubric items, never the items. Knowing there are
            # three things to cover is part of the question; knowing what they
            # are is the answer.
            lines.append(f"\n*{count} things a full answer must contain.*\n")
        vocab = out.get("vocabulary")
        if isinstance(vocab, list) and vocab:
            named = ", ".join(
                f"`{v.get('name')}` ({v.get('tier')})"
                for v in vocab if isinstance(v, dict)
            )
            lines.append(f"\n*Vocabulary: {named}*\n")
        return "".join(lines)

    @staticmethod
    def _quiz_result(out: dict) -> str:
        mark = "correct" if out.get("pick_correct") else "wrong"
        lines = ["\n#### Graded\n",
                 f"\n**{out.get('diagnosis')}** — pick {mark}"]
        if verdict := out.get("reason_verdict"):
            lines.append(f", reasoning `{verdict}`")
        lines.append("\n")
        for key in ("explanation", "next_step"):
            # Released by the grading call, so no longer a secret. This is the
            # only place either appears, and it is after the answer.
            if value := out.get(key):
                lines.append(f"\n{value}\n")
        return "".join(lines)

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
