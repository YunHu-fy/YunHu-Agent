"""Bounded, standard-library OpenAI-compatible JSON/SSE response parsing.

Only a successfully returned ParsedModelResponse may be used to dispatch tools.
Text callbacks are display-only: a callback may have run before a later error.
The caller owns/ closes the response and must bound blocking socket reads (a
monotonic deadline here cannot interrupt a read already blocked in the transport).

SSE retains one event, not the complete wire stream. Default wire budgets grow
from 16 to 128 MiB; that is *not* a resident-memory allocation. The 8 MiB event
and 8..16 MiB JSON-document caps still incur transient UTF-8/Unicode/JSON object
copies, potentially tens of MiB (or more for wide Unicode) on CPython. Structural
complexity, retained semantic characters and tool arguments are separately
bounded. These are allocation bounds, not a promise of an exact process RSS.
"""
from __future__ import annotations

import http.client
import io
import json
import math
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterator


_MIB = 1024 * 1024
_MAX_TOKENS = 1_048_576
_MAX_SEMANTIC = 8 * _MIB
_JSON_MARKERS = re.compile(rb'["\\{}\[\],:]')
_NEWLINE = re.compile(rb'\r\n|\r|\n')
_SURROGATE = re.compile('[\ud800-\udfff]')
_TOOL_NAME = re.compile(r'[A-Za-z0-9_-]+\Z')
_TOOL_ID = re.compile(r'[^\s\x00-\x1f\x7f]+\Z')


class ModelStreamError(RuntimeError):
    """Sanitized model-response failure; no raw response is stored in the error."""

    retryable = False


class IncompleteModelStreamError(ModelStreamError):
    """A transport/EOF interrupted a response before a complete result existed."""

    retryable = True


class ModelStreamProtocolError(ModelStreamError):
    """A completed frame/document violates the response protocol."""


class ModelStreamLimitError(ModelStreamError):
    """Permanent budget violation; actual is the observed size, not a guess."""

    def __init__(self, resource: str, actual: int, limit: int, unit: str = "bytes") -> None:
        self.resource = resource
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"Model response limit exceeded: {resource} observed={actual} {unit}, limit={limit} {unit}.")


class ModelOutputTruncatedError(ModelStreamError):
    """The server explicitly exhausted its output-token budget (not transport EOF)."""

    finish_reason = "length"

    def __init__(self) -> None:
        super().__init__("Model generation stopped with finish_reason=length; the response is truncated and no tools may execute.")


class ModelStreamDeadlineError(ModelStreamError, TimeoutError):
    """The caller's absolute monotonic deadline expired."""


@dataclass(frozen=True)
class StreamLimits:
    """Optional dynamic budgets plus independently tunable hard safety bounds.

    None budgets resolve from max_output_tokens at parse time. A token is not a
    character: 32 chars/token is a generous safety allowance, not token counting.
    Semantic characters include visible text, discarded reasoning and all tool
    arguments together. Each tool still has its own 300,000-character ceiling.
    Custom limits may be lower, but cannot exceed the module's hard ceilings.

    The first nonempty text delta flushes immediately. Subsequent on_text calls
    batch at text_flush_chars (default 2,048 Unicode characters) or
    text_flush_interval seconds at the next parser/read checkpoint. There is no
    background timer. Successful completion flushes the final short batch.
    """

    max_wire_bytes: int | None = None
    max_event_bytes: int = 8 * _MIB
    max_json_bytes: int | None = None
    max_text_chars: int | None = None
    max_semantic_chars: int | None = None
    max_tool_argument_chars: int = 300_000
    max_tools: int = 8
    max_tool_name_chars: int = 100
    max_tool_id_chars: int = 200
    max_json_depth: int = 64
    max_json_items: int = 100_000
    read_chunk_bytes: int = 64 * 1024
    text_flush_chars: int = 2048
    text_flush_interval: float = 0.1

    @classmethod
    def for_output_tokens(cls, max_output_tokens: int = 4096, **overrides: Any) -> "StreamLimits":
        """Return fully resolved limits, optionally with explicit lower budgets."""
        return cls(**overrides).resolved(max_output_tokens)

    def resolved(self, max_output_tokens: int = 4096) -> "StreamLimits":
        if type(max_output_tokens) is not int or not 0 < max_output_tokens <= _MAX_TOKENS:
            raise ValueError("max_output_tokens must be an integer in 1..1048576")
        text = min(_MAX_SEMANTIC, max(4096, max_output_tokens * 32))
        result = replace(
            self,
            max_wire_bytes=self.max_wire_bytes if self.max_wire_bytes is not None else min(128 * _MIB, max(16 * _MIB, max_output_tokens * 1024)),
            max_text_chars=self.max_text_chars if self.max_text_chars is not None else text,
            max_semantic_chars=self.max_semantic_chars if self.max_semantic_chars is not None else max(text, self.max_text_chars or 0, 300_000),
            max_json_bytes=self.max_json_bytes if self.max_json_bytes is not None else min(16 * _MIB, max(8 * _MIB, max(text, self.max_semantic_chars or 0) * 6 + _MIB)),
        )
        ceilings = {
            "max_wire_bytes": 128 * _MIB, "max_event_bytes": 16 * _MIB,
            "max_json_bytes": 16 * _MIB, "max_text_chars": _MAX_SEMANTIC,
            "max_semantic_chars": _MAX_SEMANTIC, "max_tool_argument_chars": 300_000,
            "max_tools": 8, "max_tool_name_chars": 100, "max_tool_id_chars": 200,
            "max_json_depth": 128, "max_json_items": 100_000,
            "read_chunk_bytes": 64 * 1024, "text_flush_chars": 64 * 1024,
        }
        for name, ceiling in ceilings.items():
            value = getattr(result, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(f"{name} must be a positive integer no greater than {ceiling}")
        interval = result.text_flush_interval
        if isinstance(interval, bool) or not isinstance(interval, (float, int)) or not math.isfinite(interval) or interval < 0:
            raise ValueError("text_flush_interval must be a finite nonnegative number")
        return result


@dataclass(frozen=True)
class ParsedModelResponse:
    content: str
    tool_calls: list[dict[str, str]]
    usage: dict[str, Any]
    metadata: dict[str, Any]
    finish_reason: str | None = None


class _Guard:
    def __init__(self, check_cancelled: Callable[[], Any] | None, deadline: float | None, clock: Callable[[], float]) -> None:
        self.check_cancelled = check_cancelled
        self.deadline = deadline
        self.clock = clock
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            raise ValueError("deadline must be a finite absolute monotonic timestamp or None")

    def check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()  # Caller cancellation exceptions deliberately pass through.
        if self.deadline is not None and self.clock() >= self.deadline:
            raise ModelStreamDeadlineError("Model response deadline exceeded; no tools may execute.")


def _limit(resource: str, actual: int, limit: int, unit: str = "bytes") -> None:
    if actual > limit:
        raise ModelStreamLimitError(resource, actual, limit, unit)


class _Reader:
    def __init__(self, response: Any, limits: StreamLimits, guard: _Guard) -> None:
        # HTTPResponse.read1 returns available data without waiting to fill 64 KiB.
        self.read_fn = getattr(response, "read1", None)
        if not callable(self.read_fn):
            self.read_fn = getattr(response, "read", None)
        if not callable(self.read_fn):
            raise TypeError("response must provide bounded read(size) or read1(size)")
        self.limits = limits
        self.guard = guard
        self.wire_bytes = 0
        self.before_read: Callable[[], Any] | None = None

    def read(self, maximum: int | None = None) -> bytes:
        self.guard.check()
        if self.before_read is not None:
            self.before_read()
        requested = min(self.limits.read_chunk_bytes, self.limits.max_wire_bytes - self.wire_bytes + 1)
        if maximum is not None:
            requested = min(requested, maximum)
        failed = False
        try:
            data = self.read_fn(requested)
        except (OSError, http.client.HTTPException, EOFError):
            failed = True
            data = b""
        self.guard.check()
        if failed:
            # Never chain transport exceptions: some transports include request data.
            raise IncompleteModelStreamError("Model response transport interrupted; no tools may execute.")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ModelStreamProtocolError("Model response transport did not return bytes.")
        self.wire_bytes += len(data)
        _limit("wire_bytes", self.wire_bytes, self.limits.max_wire_bytes)
        if len(data) > requested:
            raise ModelStreamProtocolError("Model response transport ignored its bounded read size.")
        return bytes(data) if not isinstance(data, bytes) else data


def _events(reader: _Reader, limits: StreamLimits) -> Iterator[tuple[bytearray, bool]]:
    """Yield SSE data payloads plus whether an empty-line frame delimiter existed."""
    buffer = bytearray()
    event = bytearray()
    event_wire = 0
    data_seen = False
    first_line = True
    cursor = 0
    eof = False
    while True:
        reader.guard.check()
        match = _NEWLINE.search(buffer, cursor)
        # A CR at a chunk boundary may be the first half of CRLF.
        if match is not None and match.group() == b"\r" and match.end() == len(buffer) and not eof:
            match = None
        if match is not None or (eof and cursor < len(buffer)):
            end = match.start() if match is not None else len(buffer)
            after = match.end() if match is not None else end
            event_wire += after - cursor
            _limit("event_bytes", event_wire, limits.max_event_bytes)
            start = cursor
            if first_line:
                if buffer[start:start + 3] == b"\xef\xbb\xbf":
                    start += 3
                first_line = False
            blank = start == end
            if not blank:
                if buffer[start:start + 5] == b"data:":
                    payload_start = start + 5
                    if payload_start < end and buffer[payload_start] == 32:
                        payload_start += 1
                elif end - start == 4 and buffer[start:end] == b"data":
                    payload_start = end
                else:
                    payload_start = None  # Comments, heartbeats and unknown SSE fields.
                if payload_start is not None:
                    if data_seen:
                        event.append(10)
                    event.extend(memoryview(buffer)[payload_start:end])
                    data_seen = True
            cursor = after
            if blank:
                complete = event if data_seen else None
                event = bytearray()
                data_seen = False
                event_wire = 0
                del buffer[:cursor]
                cursor = 0
                if complete is not None:
                    yield complete, True
            continue
        if cursor:
            del buffer[:cursor]
            cursor = 0
        _limit("event_bytes", event_wire + len(buffer), limits.max_event_bytes)
        if eof:
            if data_seen:
                yield event, False  # Compatible with a final frame lacking a blank line.
            return
        chunk = reader.read()
        if chunk:
            buffer.extend(chunk)
        else:
            eof = True


def _json_complexity(data: bytes | bytearray, limits: StreamLimits) -> None:
    """Reject pathological nesting/item counts before json.loads allocates objects."""
    depth = 0
    items = 0
    in_string = False
    skip_until = -1
    for match in _JSON_MARKERS.finditer(data):
        pos = match.start()
        value = data[pos]
        if in_string:
            if pos < skip_until:
                continue
            if value == 92:
                skip_until = pos + 2
            elif value == 34:
                in_string = False
            continue
        if value == 34:
            in_string = True
            items += 1
        elif value in (123, 91):
            depth += 1
            items += 1
            _limit("json_depth", depth, limits.max_json_depth, "levels")
        elif value in (125, 93):
            depth -= 1
        elif value in (44, 58):
            items += 1
        _limit("json_items", items, limits.max_json_items, "items")


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _load_json(data: bytes | bytearray, limits: StreamLimits, *, incomplete_ok: bool = False) -> Any:
    _json_complexity(data, limits)
    failure: str | None = None
    truncated = False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        truncated = incomplete_ok and exc.end == len(data) and exc.reason == "unexpected end of data"
        failure = "Model response contains invalid UTF-8."
    if failure is None:
        try:
            return json.loads(text, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            stripped = text.rstrip()
            truncated = incomplete_ok and (
                exc.pos >= len(stripped) or exc.msg.startswith("Unterminated string")
                or (stripped.startswith(("{", "[")) and not stripped.endswith(("}", "]")))
            )
            failure = "Model response contains invalid JSON."
        except (ValueError, RecursionError):
            failure = "Model response contains unsupported JSON values."
    # Raise outside handlers so raw JSON/transport exceptions are not chained.
    if truncated:
        raise IncompleteModelStreamError("Model response ended inside a JSON/UTF-8 value; no tools may execute.")
    raise ModelStreamProtocolError(failure)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SURROGATE.search(value) is not None:
        raise ModelStreamProtocolError(f"Model response {field} must be valid Unicode text.")
    return value


_USAGE_SCALARS = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens", "cached_tokens"}
_USAGE_DETAILS = {
    "prompt_tokens_details": {"cached_tokens", "audio_tokens"},
    "completion_tokens_details": {"reasoning_tokens", "audio_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens"},
    "input_tokens_details": {"cached_tokens", "audio_tokens"},
    "output_tokens_details": {"reasoning_tokens", "audio_tokens"},
}


class _Call:
    def __init__(self) -> None:
        self.parts = {key: io.StringIO() for key in ("id", "name", "arguments")}
        self.sizes = {key: 0 for key in self.parts}

    def append(self, key: str, value: str, maximum: int) -> None:
        size = self.sizes[key] + len(value)
        _limit(f"tool_{key}_chars", size, maximum, "characters")
        self.sizes[key] = size
        self.parts[key].write(value)

    def result(self) -> dict[str, str]:
        return {key: value.getvalue() for key, value in self.parts.items()}


class _State:
    def __init__(self, limits: StreamLimits, guard: _Guard, on_text: Callable[[str], Any] | None) -> None:
        self.limits = limits
        self.guard = guard
        self.on_text = on_text
        self.text = io.StringIO()
        self.pending = io.StringIO() if on_text is not None else None
        self.pending_chars = 0
        self.last_flush = guard.clock()
        self.first_text_flushed = False
        self.text_chars = 0
        self.reasoning_chars = 0
        self.argument_chars = 0
        self.semantic_chars = 0
        self.calls: dict[int, _Call] = {}
        self.usage: dict[str, Any] = {}
        self.saw_choice = False
        self.finished = False
        self.finish_reason: str | None = None
        self.event_count = 0

    def flush(self, *, due_only: bool = False) -> None:
        if not self.pending_chars:
            return
        if due_only and self.guard.clock() - self.last_flush < self.limits.text_flush_interval:
            return
        self.guard.check()
        value = self.pending.getvalue()
        self.pending = io.StringIO()
        self.pending_chars = 0
        self.on_text(value)
        self.guard.check()
        self.last_flush = self.guard.clock()

    def semantic(self, size: int) -> None:
        actual = self.semantic_chars + size
        _limit("semantic_chars", actual, self.limits.max_semantic_chars, "characters")
        self.semantic_chars = actual

    def add_text(self, value: str) -> None:
        if not value:
            return
        _limit("text_chars", self.text_chars + len(value), self.limits.max_text_chars, "characters")
        self.semantic(len(value))
        self.text_chars += len(value)
        self.text.write(value)
        if self.pending is not None:
            offset = 0
            while offset < len(value):
                self.guard.check()
                count = min(self.limits.text_flush_chars - self.pending_chars, len(value) - offset)
                self.pending.write(value[offset:offset + count])
                self.pending_chars += count
                offset += count
                if self.pending_chars >= self.limits.text_flush_chars:
                    self.flush()
            if not self.first_text_flushed and self.pending_chars:
                self.flush()
            self.first_text_flushed = True

    def add_usage(self, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise ModelStreamProtocolError("Model usage must be an object.")
        for key in _USAGE_SCALARS | _USAGE_DETAILS.keys():
            item = value.get(key)
            if item is None:
                continue
            if key in _USAGE_DETAILS:
                if not isinstance(item, dict):
                    raise ModelStreamProtocolError("Model usage details must be an object.")
                target = self.usage.setdefault(key, {})
                for subkey in _USAGE_DETAILS[key]:
                    if item.get(subkey) is not None:
                        target[subkey] = self.usage_count(item[subkey])
            else:
                self.usage[key] = self.usage_count(item)

    @staticmethod
    def usage_count(value: Any) -> int:
        if type(value) is not int or value < 0 or value > (1 << 63) - 1:
            raise ModelStreamProtocolError("Model usage counts must be nonnegative 64-bit integers.")
        return value

    def add_calls(self, value: Any, streaming: bool) -> None:
        if value is None:
            return
        if not isinstance(value, list):
            raise ModelStreamProtocolError("Model tool_calls must be an array.")
        _limit("tool_count", len(value), self.limits.max_tools, "tools")
        for position, item in enumerate(value):
            self.guard.check()
            if not isinstance(item, dict):
                raise ModelStreamProtocolError("Model tool call must be an object.")
            if streaming and "index" not in item:
                raise ModelStreamProtocolError("Streaming tool call is missing its integer index.")
            index = item.get("index", position)
            if type(index) is not int or index < 0:
                raise ModelStreamProtocolError("Model tool index must be a nonnegative integer.")
            _limit("tool_index", index, self.limits.max_tools - 1, "index")
            if not streaming and index != position:
                raise ModelStreamProtocolError("JSON tool indices must be contiguous and ordered.")
            if item.get("type") not in (None, "function"):
                raise ModelStreamProtocolError("Only function tool calls are supported.")
            function = item.get("function", {})
            if not isinstance(function, dict):
                raise ModelStreamProtocolError("Model tool function must be an object.")
            call = self.calls.setdefault(index, _Call())
            for key, source, maximum in (
                ("id", item, self.limits.max_tool_id_chars),
                ("name", function, self.limits.max_tool_name_chars),
                ("arguments", function, self.limits.max_tool_argument_chars),
            ):
                part = source.get(key)
                if part is None:
                    continue
                part = _string(part, "tool field")
                if key == "arguments":
                    self.semantic(len(part))
                    self.argument_chars += len(part)
                call.append(key, part, maximum)

    def apply(self, body: Any, *, streaming: bool) -> None:
        self.guard.check()
        if not isinstance(body, dict):
            raise ModelStreamProtocolError("Model response JSON must be an object.")
        if body.get("error") is not None:
            raise ModelStreamProtocolError("Model service reported a generation error; no tools may execute.")
        self.add_usage(body.get("usage"))
        choices = body.get("choices", [])
        if not isinstance(choices, list):
            raise ModelStreamProtocolError("Model choices must be an array.")
        if not choices:
            if not streaming:
                raise ModelStreamProtocolError("JSON model response is missing its completion choice.")
            return  # Usage-only chunks and provider heartbeats.
        if len(choices) != 1 or not isinstance(choices[0], dict):
            raise ModelStreamProtocolError("Exactly one model completion choice is supported.")
        choice = choices[0]
        if "index" in choice and (type(choice["index"]) is not int or choice["index"] != 0):
            raise ModelStreamProtocolError("Model completion choice index must be zero.")
        self.saw_choice = True
        delta = choice.get("delta", {}) if streaming else choice.get("message")
        if not isinstance(delta, dict):
            raise ModelStreamProtocolError("Model completion message/delta must be an object.")
        if self.finished and any(delta.get(key) for key in ("content", "tool_calls", "reasoning_content", "reasoning")):
            raise ModelStreamProtocolError("Model emitted output after its finish_reason.")
        text = delta.get("content")
        if text is not None:
            self.add_text(_string(text, "content"))
        for key in ("reasoning_content", "reasoning"):
            reasoning = delta.get(key)
            if reasoning is not None:
                reasoning = _string(reasoning, "reasoning")
                self.semantic(len(reasoning))
                self.reasoning_chars += len(reasoning)
        self.add_calls(delta.get("tool_calls"), streaming)
        reason = choice.get("finish_reason")
        if reason is not None:
            reason = _string(reason, "finish_reason")
            if not reason or len(reason) > 100:
                raise ModelStreamProtocolError("Model finish_reason is invalid.")
            if reason == "length":
                raise ModelOutputTruncatedError()
            if reason == "content_filter":
                raise ModelStreamProtocolError("Model response was stopped by content_filter; no tools may execute.")
            if self.finish_reason is not None and self.finish_reason != reason:
                raise ModelStreamProtocolError("Model returned conflicting finish reasons.")
            self.finish_reason = reason
            self.finished = True
        self.flush(due_only=True)

    def result(self, reader: _Reader, protocol: str, terminated_by: str) -> ParsedModelResponse:
        self.guard.check()
        if not self.saw_choice:
            raise ModelStreamProtocolError("Model response did not contain a completion choice.")
        if sorted(self.calls) != list(range(len(self.calls))):
            raise ModelStreamProtocolError("Model tool indices contain a gap; no tools may execute.")
        calls: list[dict[str, str]] = []
        identifiers: set[str] = set()
        for index in sorted(self.calls):
            self.guard.check()
            call = self.calls[index].result()
            if not _TOOL_ID.fullmatch(call["id"]) or not _TOOL_NAME.fullmatch(call["name"]):
                raise ModelStreamProtocolError("Model tool call is missing a valid id/name; no tools may execute.")
            if call["id"] in identifiers:
                raise ModelStreamProtocolError("Model tool call ids are not unique; no tools may execute.")
            identifiers.add(call["id"])
            arguments = _load_json(call["arguments"].encode("utf-8"), self.limits)
            if not isinstance(arguments, dict):
                raise ModelStreamProtocolError("Model tool arguments must be a complete JSON object; no tools may execute.")
            calls.append(call)
        if self.finish_reason in ("tool_calls", "function_call") and not calls:
            raise ModelStreamProtocolError("Model finished for tool calls but supplied no valid tools.")
        self.flush()
        self.guard.check()
        return ParsedModelResponse(
            content=self.text.getvalue(), tool_calls=calls, usage=self.usage,
            finish_reason=self.finish_reason,
            metadata={"protocol": protocol, "terminated_by": terminated_by,
                      "wire_bytes": reader.wire_bytes, "event_count": self.event_count,
                      "text_chars": self.text_chars, "reasoning_chars": self.reasoning_chars,
                      "tool_argument_chars": self.argument_chars, "semantic_chars": self.semantic_chars},
        )


def parse_model_response(
    response: Any,
    *,
    max_output_tokens: int = 4096,
    limits: StreamLimits | None = None,
    on_text: Callable[[str], Any] | None = None,
    check_cancelled: Callable[[], Any] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    content_type: str | None = None,
) -> ParsedModelResponse:
    """Parse a bounded byte response without dispatching or exposing partial tools.

    response supplies read1(size) or read(size), and optionally HTTP getheader.
    Content-Type selects SSE; all other types use the bounded JSON-document path.
    HTTP status validation, connection ownership and transport timeout/abort stay
    with the caller. deadline is an absolute value in clock's monotonic domain.
    check_cancelled may raise a caller-defined exception, which is not wrapped.
    on_text exceptions likewise propagate, and callbacks are always ordered.

    IncompleteModelStreamError is retryable. ModelStreamLimitError, protocol
    errors and explicit ModelOutputTruncatedError (finish_reason=length) are not.
    A successful return requires [DONE], finish_reason, or a complete JSON body,
    plus validation of the *whole* tool-call group. A response containing only
    partial text without an SSE terminator is never reported as successful.
    """
    if limits is not None and not isinstance(limits, StreamLimits):
        raise TypeError("limits must be StreamLimits or None")
    limits = (limits or StreamLimits()).resolved(max_output_tokens)
    guard = _Guard(check_cancelled, deadline, clock)
    guard.check()
    reader = _Reader(response, limits, guard)
    state = _State(limits, guard, on_text)
    reader.before_read = lambda: state.flush(due_only=True)
    if content_type is None:
        getheader = getattr(response, "getheader", None)
        content_type = getheader("Content-Type", "") if callable(getheader) else ""
    if not isinstance(content_type, str):
        raise ModelStreamProtocolError("Model Content-Type must be text.")
    if "text/event-stream" not in content_type.lower():
        document = bytearray()
        while True:
            chunk = reader.read(limits.max_json_bytes - len(document) + 1)
            if not chunk:
                break
            document.extend(chunk)
            _limit("json_bytes", len(document), limits.max_json_bytes)
        if not document.strip():
            raise IncompleteModelStreamError("Model response ended before its JSON document; no tools may execute.")
        body = _load_json(document, limits, incomplete_ok=True)
        state.apply(body, streaming=False)
        return state.result(reader, "json", "json_document")

    terminated_by: str | None = None
    try:
        for payload, framed in _events(reader, limits):
            guard.check()
            state.event_count += 1
            stripped = payload.strip()
            if not stripped:
                continue
            if stripped == b"[DONE]":
                terminated_by = "done"
                break
            state.apply(_load_json(payload, limits, incomplete_ok=not framed), streaming=True)
    except IncompleteModelStreamError:
        if not state.finished:
            raise
        # finish_reason already closes the completion. An optional usage trailer
        # lost at EOF must not turn a complete, validated tool group into a retry.
        guard.check()
    if terminated_by is None:
        if not state.finished:
            raise IncompleteModelStreamError("Model event stream ended before completion; no tools may execute.")
        terminated_by = "finish_reason"
    return state.result(reader, "sse", terminated_by)
