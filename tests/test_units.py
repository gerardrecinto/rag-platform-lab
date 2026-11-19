import base64
import json

import httpx
import pytest
from botocore.stub import Stubber

from app import chat, ingest_pb2, providers
from app.chunk import chunk
from app.embed import embed
from app.redact import redact


def test_redact_removes_identifiers_and_counts():
    text = "Call 619-555-0142 or mail jo@example.com. SSN 123-45-6789, MRN: 00123456, DOB: 4/9/1980."
    clean, n = redact(text)
    assert n == 5
    for leaked in ("619-555-0142", "jo@example.com", "123-45-6789", "00123456", "4/9/1980"):
        assert leaked not in clean
    assert "[SSN]" in clean and "[EMAIL]" in clean


def test_redact_leaves_plain_text_alone():
    assert redact("Sleep hygiene helps with insomnia.") == ("Sleep hygiene helps with insomnia.", 0)


def test_chunk_overlaps_and_covers_everything():
    words = [f"w{i}" for i in range(130)]
    pieces = chunk(" ".join(words), size=60, overlap=10)
    assert len(pieces) == 3
    assert pieces[0].split()[-10:] == pieces[1].split()[:10]
    assert pieces[-1].split()[-1] == "w129"


def test_chunk_rejects_bad_overlap():
    with pytest.raises(ValueError):
        chunk("a b c", size=5, overlap=5)


def test_embedding_is_deterministic_unit_length_and_similar_for_similar_text():
    a, b, c = embed("cbt for insomnia"), embed("insomnia and cbt"), embed("quarterly budget forecast")
    assert a == embed("cbt for insomnia")
    assert abs(sum(x * x for x in a) - 1) < 1e-9
    dot = lambda x, y: sum(p * q for p, q in zip(x, y))  # noqa: E731
    assert dot(a, b) > dot(a, c)


def test_protobuf_round_trip_through_the_celery_envelope():
    msg = ingest_pb2.IngestJob(job_id="j1", source="doc", text="hello")
    wire = base64.b64encode(msg.SerializeToString()).decode()
    back = ingest_pb2.IngestJob.FromString(base64.b64decode(wire))
    assert (back.job_id, back.source, back.text) == ("j1", "doc", "hello")


def test_mock_provider_cites_first_source_and_reports_estimated_tokens():
    p = providers.MockProvider()
    out = "".join(p.stream("sys", "Sources:\n[1] CBT helps insomnia. More text.\n\nQuestion: q"))
    assert "CBT helps insomnia" in out and out.strip().endswith("[1]")
    assert p.usage[2] is True


def test_anthropic_stream_parses_text_and_real_usage():
    sse = "\n".join([
        'data: {"type":"message_start","message":{"usage":{"input_tokens":21}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":7}}', ""])
    seen = {}

    def handler(req):
        seen["key"] = req.headers["x-api-key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, text=sse)

    p = providers.AnthropicProvider("k", transport=httpx.MockTransport(handler))
    assert "".join(p.stream("s", "q")) == "Hello"
    assert p.usage == (21, 7, False) and seen["key"] == "k" and seen["body"]["stream"] is True


def test_openai_stream_parses_text_and_usage():
    sse = "\n".join([
        'data: {"choices":[{"delta":{"content":"Hi "}}]}',
        'data: {"choices":[{"delta":{"content":"there"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2}}',
        "data: [DONE]", ""])
    p = providers.OpenAIProvider("k", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=sse)))
    assert "".join(p.stream("s", "q")) == "Hi there"
    assert p.usage == (9, 2, False)


def test_provider_http_error_surfaces():
    p = providers.OpenAIProvider("k", transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow down")))
    with pytest.raises(httpx.HTTPStatusError):
        list(p.stream("s", "q"))


def test_bedrock_converse_is_streamed_in_pieces():
    import boto3
    client = boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="x", aws_secret_access_key="y")
    with Stubber(client) as stub:
        stub.add_response("converse", {
            "output": {"message": {"role": "assistant", "content": [{"text": "Sleep helps recovery."}]}},
            "usage": {"inputTokens": 30, "outputTokens": 4, "totalTokens": 34},
            "stopReason": "end_turn", "metrics": {"latencyMs": 5}})
        p = providers.BedrockProvider(client=client)
        assert "".join(p.stream("s", "q")).strip() == "Sleep helps recovery."
        assert p.usage == (30, 4, False)


def test_sse_frame_shape():
    frame = chat.sse({"type": "token", "text": "x"})
    assert frame.startswith("event: token\ndata: ") and frame.endswith("\n\n")


def test_prompt_numbers_sources():
    prompt = chat.build_prompt("why?", [{"text": "A"}, {"text": "B"}])
    assert "[1] A" in prompt and "[2] B" in prompt and prompt.endswith("Question: why?")


def test_api_rejects_missing_token_and_bad_websocket_token():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import app
    c = TestClient(app)
    assert c.post("/v1/chat/stream", json={"query": "x"}).status_code == 401
    assert c.post("/v1/ingest", json={"source": "s", "text": "t"}).status_code == 401
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/v1/chat/ws?token=wrong"):
            pass
    assert e.value.code == 4401


def test_request_validation_rejects_empty_query():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).post("/v1/chat/stream", json={"query": ""}, headers={"Authorization": "Bearer lab-token"})
    assert r.status_code == 422
