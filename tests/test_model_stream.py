from __future__ import annotations

import http.client
import itertools
import json
import tracemalloc
import unittest
from dataclasses import replace

from android_agent.model_stream import (
    IncompleteModelStreamError,
    ModelOutputTruncatedError,
    ModelStreamDeadlineError,
    ModelStreamError,
    ModelStreamLimitError,
    ModelStreamProtocolError,
    StreamLimits,
    parse_model_response,
)


MIB = 1024 * 1024


def event(delta=None, finish=None, **extra):
    value = {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    value.update(extra)
    return b"data: " + json.dumps(value, ensure_ascii=False).encode() + b"\n\n"


def document(content="ok", calls=None, finish="stop", **extra):
    message = {"content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return json.dumps({"choices": [{"message": message, "finish_reason": finish}], **extra}, ensure_ascii=False).encode()


def tool(index=0, identifier="call_0", name="workspace_write", arguments='{"path":"a","content":"ok"}'):
    return {"index": index, "id": identifier, "type": "function", "function": {"name": name, "arguments": arguments}}


class Response:
    """A lazy body that fails any unbounded read and simulates transport splits."""

    def __init__(self, parts, content_type="text/event-stream", chunk_size=65536, on_read=None):
        self.parts = iter([parts] if isinstance(parts, bytes) else parts)
        self.buffer = b""
        self.content_type = content_type
        self.chunk_size = chunk_size
        self.requests = []
        self.total_read = 0
        self.on_read = on_read

    def getheader(self, name, default=""):
        return self.content_type if name.lower() == "content-type" else default

    def read1(self, size):
        if type(size) is not int or not 0 < size <= 65536:
            raise AssertionError("every read must be bounded")
        self.requests.append(size)
        if self.on_read:
            self.on_read()
        while not self.buffer:
            part = next(self.parts, None)
            if part is None:
                return b""
            if isinstance(part, Exception):
                raise part
            self.buffer = part
        count = min(size, self.chunk_size, len(self.buffer))
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        self.total_read += len(result)
        return result


class ModelStreamTests(unittest.TestCase):
    def parse(self, body, **kwargs):
        return parse_model_response(Response(body), **kwargs)

    def test_more_than_two_mib_many_small_deltas(self):
        count = 26000
        part = event({"content": "中"})
        self.assertGreater(len(part) * count, 2 * MIB)
        response = Response(itertools.chain(itertools.repeat(part, count), [b"data: [DONE]\n\n"]))
        output = []
        result = parse_model_response(response, max_output_tokens=8192, on_text=output.append,
                                      limits=StreamLimits(text_flush_interval=3600))
        self.assertEqual(result.content, "中" * count)
        self.assertEqual("".join(output), result.content)
        self.assertEqual(output[0], "中")
        self.assertEqual(len(output), 1 + (count - 1 + 2047) // 2048)
        self.assertTrue(all(0 < n <= 65536 for n in response.requests))
        self.assertGreater(result.metadata["wire_bytes"], 2 * MIB)

    def test_event_beyond_old_single_line_limit(self):
        value = "中文" * 150000
        frame = event({"content": value})
        self.assertGreater(len(frame), 512 * 1024)
        output = []
        result = self.parse([frame, b"data: [DONE]\n\n"], max_output_tokens=16384, on_text=output.append)
        self.assertEqual(result.content, value)
        self.assertEqual("".join(output), value)
        self.assertLessEqual(max(map(len, output)), 2048)

    def test_reasoning_stream_is_counted_but_never_rendered(self):
        value = "private thought " * 100
        frames = itertools.chain((event({"reasoning_content": value}) for _ in range(1800)),
                                 [event({"reasoning": "尾巴"}), event({"content": "answer"}, "stop"),
                                  b'data: {"choices":[],"usage":{"completion_tokens":1900,"completion_tokens_details":{"reasoning_tokens":1899}}}\n\n',
                                  b"data: [DONE]\n\n"])
        output = []
        result = self.parse(frames, max_output_tokens=131072, on_text=output.append)
        self.assertEqual(result.content, "answer")
        self.assertEqual(output, ["answer"])
        self.assertEqual(result.metadata["reasoning_chars"], len(value) * 1800 + 2)
        self.assertNotIn("private thought", repr(result))
        self.assertEqual(result.usage["completion_tokens_details"]["reasoning_tokens"], 1899)

    def test_utf8_across_every_byte_and_multiline_crlf_comments(self):
        body = ('\ufeff: heartbeat\r\nevent: message\r\nid: harmless\r\n'
                'data: {"choices": [\r\n: comment inside event\r\n'
                'data: {"delta": {"content": "中文🙂"}}]}\r\n\r\n'
                ': ping\r\n\r\ndata: [DONE]\r\n\r\n').encode()
        result = parse_model_response(Response(body, chunk_size=1))
        self.assertEqual(result.content, "中文🙂")
        self.assertEqual(result.metadata["terminated_by"], "done")

    def test_bare_cr_and_final_frame_without_empty_line(self):
        frame = event({"content": "x"}).replace(b"\n", b"\r")
        result = self.parse([frame, b"data: [DONE]"])
        self.assertEqual(result.content, "x")

    def test_empty_data_heartbeats_and_unknown_fields(self):
        result = self.parse([b": ping\n\nretry: 123\n\ndata:\n\ndata\n\n",
                             event({"content": "ok"}), b"data: [DONE]\n\n"])
        self.assertEqual(result.content, "ok")

    def test_finish_reason_without_done(self):
        result = self.parse(event({"content": "ok"}, "stop"))
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.metadata["terminated_by"], "finish_reason")

    def test_usage_trailer_merges_safe_fields(self):
        frames = [event({"content": "ok"}, "stop", usage={"prompt_tokens": 4}),
                  b'data: {"choices":[],"usage":{"completion_tokens":2,"total_tokens":6,"token":"SECRET"},"token":"SECRET"}\n\n',
                  b"data: [DONE]\n\n"]
        result = self.parse(frames)
        self.assertEqual(result.usage, {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6})
        self.assertNotIn("SECRET", repr(result))

    def test_interleaved_tool_fragments_are_sorted_and_validated(self):
        first = {"index": 1, "id": "call_", "function": {"name": "workspace_", "arguments": '{"x":'}}
        second = tool(0, "call_0", "workspace_list", "{}")
        final = {"index": 1, "id": "1", "function": {"name": "write", "arguments": "1}"}}
        result = self.parse([event({"tool_calls": [first, second]}), event({"tool_calls": [final]}, "tool_calls"), b"data: [DONE]\n\n"])
        self.assertEqual(result.tool_calls, [{"id": "call_0", "name": "workspace_list", "arguments": "{}"},
                                            {"id": "call_1", "name": "workspace_write", "arguments": '{"x":1}'}])

    def test_eight_tools_allowed_ninth_rejected(self):
        result = self.parse([event({"tool_calls": [tool(i, f"call_{i}") for i in range(8)]}), b"data: [DONE]\n\n"])
        self.assertEqual(len(result.tool_calls), 8)
        with self.assertRaises(ModelStreamLimitError) as raised:
            self.parse([event({"tool_calls": [tool(i, f"call_{i}") for i in range(9)]}), b"data: [DONE]\n\n"])
        self.assertEqual((raised.exception.actual, raised.exception.limit), (9, 8))

    def test_invalid_tool_group_is_never_returned(self):
        invalid = [
            [tool(index=1)],
            [tool(), tool(1, "call_0")],
            [tool(identifier="")],
            [tool(name="")],
            [tool(name="bad.name")],
            [tool(arguments='{"unfinished":')],
            [tool(arguments='[]')],
            [tool(index=True)],
            [{"function": {"name": "a", "arguments": "{}"}, "id": "x"}],
            [dict(tool(), type="unsupported")],
        ]
        for calls in invalid:
            with self.subTest(calls=calls), self.assertRaises(ModelStreamProtocolError):
                self.parse([event({"tool_calls": calls}), b"data: [DONE]\n\n"])

    def test_partial_text_and_tools_without_terminator_are_retryable(self):
        for delta in ({"content": "half"}, {"tool_calls": [tool()]}, {"reasoning": "half"}):
            with self.subTest(delta=delta), self.assertRaises(IncompleteModelStreamError) as raised:
                self.parse(event(delta))
            self.assertTrue(raised.exception.retryable)
            self.assertFalse(hasattr(raised.exception, "tool_calls"))

    def test_empty_or_usage_only_done_is_not_a_completion(self):
        for body in (b"data: [DONE]\n\n", b'data: {"choices":[],"usage":{"total_tokens":1}}\n\ndata: [DONE]\n\n'):
            with self.subTest(body=body), self.assertRaises(ModelStreamProtocolError):
                self.parse(body)

    def test_finish_length_is_distinct_from_transport_incomplete(self):
        for is_json in (False, True):
            body = document("partial", finish="length") if is_json else event({"content": "partial", "tool_calls": [tool()]}, "length")
            with self.subTest(is_json=is_json), self.assertRaises(ModelOutputTruncatedError) as raised:
                if is_json:
                    parse_model_response(Response(body, "application/json"))
                else:
                    self.parse(body)
            self.assertFalse(raised.exception.retryable)
            self.assertEqual(raised.exception.finish_reason, "length")

    def test_transport_errors_are_sanitized(self):
        for failure in (OSError("SECRET TOKEN"), http.client.IncompleteRead(b"SECRET TOKEN")):
            with self.subTest(failure=type(failure)), self.assertRaises(IncompleteModelStreamError) as raised:
                self.parse([event({"content": "half"}), failure])
            self.assertNotIn("SECRET", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)

    def test_finished_choice_can_survive_missing_optional_usage_trailer(self):
        result = self.parse([event({"tool_calls": [tool()]}, "tool_calls"), OSError("closed")])
        self.assertEqual(len(result.tool_calls), 1)

    def test_output_after_finish_is_protocol_error(self):
        with self.assertRaises(ModelStreamProtocolError):
            self.parse([event({"content": "ok"}, "stop"), event({"content": "unexpected"}), b"data: [DONE]\n\n"])

    def test_wire_limit_bounds_endless_small_garbage_and_heartbeats(self):
        for repeated in (b": ping\n\n", b"junk\n\n"):
            response = Response(itertools.repeat(repeated))
            with self.subTest(repeated=repeated), self.assertRaises(ModelStreamLimitError) as raised:
                parse_model_response(response, limits=StreamLimits(max_wire_bytes=4096))
            self.assertEqual(raised.exception.resource, "wire_bytes")
            self.assertEqual((raised.exception.actual, raised.exception.limit), (4097, 4096))
            self.assertEqual(response.total_read, 4097)
            self.assertFalse(raised.exception.retryable)

    def test_event_limit_bounds_one_giant_line_or_unterminated_event(self):
        for repeated in (b"x" * 256, b":x\n"):
            response = Response(itertools.repeat(repeated))
            with self.subTest(repeated=len(repeated)), self.assertRaises(ModelStreamLimitError) as raised:
                parse_model_response(response, limits=StreamLimits(max_event_bytes=4096, max_wire_bytes=100000))
            self.assertEqual(raised.exception.resource, "event_bytes")
            self.assertGreater(raised.exception.actual, raised.exception.limit)
            self.assertLessEqual(response.total_read, 4096 + 65536)

    def test_event_limit_includes_comments_and_framing(self):
        with self.assertRaises(ModelStreamLimitError) as raised:
            self.parse(b":" + b"x" * 63 + b"\n\n", limits=StreamLimits(max_event_bytes=64))
        self.assertEqual(raised.exception.resource, "event_bytes")
        self.assertEqual(raised.exception.actual, 65)

    def test_text_and_semantic_limits_are_independent_and_report_sizes(self):
        with self.assertRaises(ModelStreamLimitError) as raised:
            self.parse(event({"content": "x" * 101}), limits=StreamLimits(max_text_chars=100))
        self.assertEqual((raised.exception.resource, raised.exception.actual, raised.exception.limit), ("text_chars", 101, 100))
        with self.assertRaises(ModelStreamLimitError) as raised:
            self.parse([event({"reasoning": "x" * 60}), event({"content": "x" * 41})],
                       limits=StreamLimits(max_semantic_chars=100))
        self.assertEqual((raised.exception.resource, raised.exception.actual, raised.exception.limit), ("semantic_chars", 101, 100))
        self.assertNotIn("x" * 41, str(raised.exception))

    def test_tool_argument_limit_is_characters_not_utf8_bytes(self):
        args = json.dumps({"x": "中" * 100}, ensure_ascii=False)
        allowed = StreamLimits(max_tool_argument_chars=len(args))
        result = self.parse([event({"tool_calls": [tool(arguments=args)]}), b"data: [DONE]\n\n"], limits=allowed)
        self.assertEqual(result.tool_calls[0]["arguments"], args)
        with self.assertRaises(ModelStreamLimitError) as raised:
            self.parse(event({"tool_calls": [tool(arguments=args)]}), limits=replace(allowed, max_tool_argument_chars=len(args) - 1))
        self.assertEqual((raised.exception.actual, raised.exception.limit), (len(args), len(args) - 1))

    def test_tool_id_and_name_limits(self):
        for call, resource, size, cap in ((tool(identifier="i" * 201), "tool_id_chars", 201, 200),
                                           (tool(name="n" * 101), "tool_name_chars", 101, 100)):
            with self.subTest(resource=resource), self.assertRaises(ModelStreamLimitError) as raised:
                self.parse(event({"tool_calls": [call]}))
            self.assertEqual((raised.exception.resource, raised.exception.actual, raised.exception.limit), (resource, size, cap))

    def test_default_text_budget_scales_beyond_old_64k(self):
        value = "x" * 70000
        result = self.parse([event({"content": value}), b"data: [DONE]\n\n"], max_output_tokens=4096)
        self.assertEqual(result.content, value)
        small = StreamLimits.for_output_tokens(4096)
        large = StreamLimits.for_output_tokens(131072)
        self.assertGreater(large.max_text_chars, small.max_text_chars)
        self.assertEqual(small.max_wire_bytes, 16 * MIB)
        self.assertEqual(large.max_wire_bytes, 128 * MIB)
        self.assertEqual(StreamLimits.for_output_tokens(32768).max_wire_bytes, 32 * MIB)
        self.assertEqual(small.max_event_bytes, 8 * MIB)
        self.assertLessEqual(large.max_json_bytes, 16 * MIB)

    def test_json_fallback_with_usage_tools_and_reasoning(self):
        calls = [tool()]
        del calls[0]["index"]
        value = {"choices": [{"message": {"content": "中文", "reasoning_content": "hidden", "tool_calls": calls}, "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 7, "completion_tokens": 2}}
        output = []
        result = parse_model_response(Response(json.dumps(value, ensure_ascii=False).encode(), "application/json", chunk_size=1), on_text=output.append)
        self.assertEqual(result.content, "中文")
        self.assertEqual(output, ["中文"])
        self.assertEqual(result.tool_calls[0]["name"], "workspace_write")
        self.assertEqual(result.usage["prompt_tokens"], 7)
        self.assertEqual(result.metadata["protocol"], "json")
        self.assertEqual(result.metadata["reasoning_chars"], 6)

    def test_json_read_fallback_and_content_type_override(self):
        class ReadOnly:
            def __init__(self):
                self.response = Response(document(), "application/json", chunk_size=3)

            def read(self, size):
                return self.response.read1(size)

        result = parse_model_response(ReadOnly(), content_type="application/json")
        self.assertEqual(result.content, "ok")

    def test_large_json_is_read_in_chunks(self):
        value = "中" * 200000
        response = Response(document(value), "application/json", chunk_size=4096)
        result = parse_model_response(response, max_output_tokens=16384)
        self.assertEqual(result.content, value)
        self.assertGreater(len(response.requests), 2)
        self.assertLessEqual(max(response.requests), 65536)

    def test_json_document_cap_is_independent_of_wire_cap(self):
        response = Response(itertools.repeat(b" " * 256), "application/json")
        with self.assertRaises(ModelStreamLimitError) as raised:
            parse_model_response(response, limits=StreamLimits(max_json_bytes=4096, max_wire_bytes=100000))
        self.assertEqual((raised.exception.resource, raised.exception.actual, raised.exception.limit), ("json_bytes", 4097, 4096))

    def test_json_truncation_and_malformed_complete_event_are_distinct(self):
        for raw in (b"", b'{"choices":', b'{"choices":[{"message":{"content":"part', b'{"choices":[{"message":{"content":"\xe4\xb8'):
            with self.subTest(raw=raw), self.assertRaises(IncompleteModelStreamError):
                parse_model_response(Response(raw, "application/json"))
        for raw in (b"data: {invalid SECRET}\n\n", b'data: {"x":"\xff"}\n\n', b"data: []\n\n"):
            with self.subTest(raw=raw), self.assertRaises(ModelStreamProtocolError) as raised:
                self.parse(raw)
            self.assertNotIn("SECRET", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
        with self.assertRaises(IncompleteModelStreamError):
            self.parse(b'data: {"choices":[')

    def test_json_structure_limits_before_object_allocation(self):
        for raw, limits, resource in ((b"[" * 65 + b"0" + b"]" * 65, StreamLimits(), "json_depth"),
                                      (b"[" + b"0," * 100 + b"0]", StreamLimits(max_json_items=50), "json_items")):
            with self.subTest(resource=resource), self.assertRaises(ModelStreamLimitError) as raised:
                parse_model_response(Response(raw, "application/json"), limits=limits)
            self.assertEqual(raised.exception.resource, resource)

    def test_escaped_json_string_not_mistaken_for_structure(self):
        value = '\\"[{]}:,' * 500
        result = self.parse([event({"content": value}), b"data: [DONE]\n\n"], limits=StreamLimits(max_json_depth=8))
        self.assertEqual(result.content, value)

    def test_invalid_shape_nonfinite_surrogate_or_usage_rejected(self):
        bodies = [b"data: NaN\n\n", b'data: {"choices":{},"error":null}\n\n',
                  event({"content": 3}), b'data: {"choices":[{"delta":{"content":"\\ud800"}}]}\n\n',
                  event({}, usage={"total_tokens": True}), b'data: {"error":{"message":"SECRET"}}\n\n',
                  event({"reasoning": {"token": "SECRET"}})]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ModelStreamProtocolError) as raised:
                self.parse(body)
            self.assertNotIn("SECRET", str(raised.exception))

    def test_content_filter_does_not_return_tools(self):
        with self.assertRaises(ModelStreamProtocolError):
            self.parse(event({"tool_calls": [tool()]}, "content_filter"))

    def test_deadline_and_cancellation_checks_surround_reads_and_callbacks(self):
        now = [0.0]
        response = Response([event({"content": "x"})], on_read=lambda: now.__setitem__(0, 2.0))
        with self.assertRaises(ModelStreamDeadlineError) as raised:
            parse_model_response(response, deadline=1.0, clock=lambda: now[0])
        self.assertIsInstance(raised.exception, TimeoutError)

        class Cancelled(Exception):
            pass

        cancelled = [False]
        callbacks = []

        def check():
            if cancelled[0]:
                raise Cancelled("caller sentinel")

        def on_text(text):
            callbacks.append(text)
            cancelled[0] = True

        with self.assertRaises(Cancelled):
            self.parse([event({"content": "abcdef"}), b"data: [DONE]\n\n"],
                       limits=StreamLimits(text_flush_chars=3), on_text=on_text, check_cancelled=check)
        self.assertEqual(callbacks, ["abc"])

    def test_callback_time_flush_and_final_flush_are_ordered(self):
        now = [0.0]
        output = []
        parts = [event({"content": "first"}), event({"content": "second"}), b"data: [DONE]\n\n"]
        response = Response(parts, on_read=lambda: now.__setitem__(0, now[0] + 0.2))
        result = parse_model_response(response, on_text=output.append, clock=lambda: now[0])
        self.assertEqual(output, ["first", "second"])
        self.assertEqual("".join(output), result.content)

    def test_empty_initial_delta_preserves_immediate_first_text(self):
        output = []
        def parts():
            yield event({"role": "assistant", "content": ""})
            yield event({"content": "first"})
            self.assertEqual(output, ["first"])
            yield b"data: [DONE]\n\n"
        result = self.parse(parts(), on_text=output.append, limits=StreamLimits(text_flush_interval=3600))
        self.assertEqual(result.content, "first")

    def test_callback_exceptions_propagate(self):
        class CallbackError(Exception):
            pass

        def callback(text):
            raise CallbackError("caller")

        with self.assertRaises(CallbackError):
            self.parse([event({"content": "x"}), b"data: [DONE]\n\n"], on_text=callback)

    def test_limits_configuration_cannot_remove_hard_bounds(self):
        for limits in (StreamLimits(max_tools=9), StreamLimits(max_wire_bytes=129 * MIB),
                       StreamLimits(max_event_bytes=17 * MIB), StreamLimits(max_tool_argument_chars=300001),
                       StreamLimits(read_chunk_bytes=0), StreamLimits(text_flush_interval=float("inf"))):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.parse(b"", limits=limits)
        for value in (True, 0, -1, 1048577):
            with self.subTest(tokens=value), self.assertRaises(ValueError):
                self.parse(b"", max_output_tokens=value)

    def test_transport_must_honor_bounded_bytes_contract(self):
        class BadReader:
            def read(self, size):
                return b"x" * (size + 1)

        with self.assertRaises(ModelStreamProtocolError):
            parse_model_response(BadReader())

    def test_streaming_wire_budget_does_not_equal_retained_memory(self):
        heartbeat = b": " + b"x" * 1000 + b"\n\n"
        response = Response(itertools.chain(itertools.repeat(heartbeat, 12000),
                                           [event({"content": "ok"}), b"data: [DONE]\n\n"]))
        tracemalloc.start()
        try:
            result = parse_model_response(response)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertGreater(result.metadata["wire_bytes"], 10 * MIB)
        # Includes the fake transport's per-read bookkeeping; still no whole body.
        self.assertLess(peak, 4 * MIB)
        self.assertEqual(result.content, "ok")


if __name__ == "__main__":
    unittest.main()
