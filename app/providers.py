"""Model providers. Each stream() yields text pieces; usage is set on the provider after the stream ends."""
import json

import httpx


class Provider:
    name = "base"
    model = ""

    def __init__(self):
        self.usage = None  # (prompt_tokens, completion_tokens, estimated)

    def stream(self, system, prompt):
        raise NotImplementedError


def estimate(text):
    return max(1, len(text) // 4)


class MockProvider(Provider):
    """Answers from the first source in the prompt. No network, no key."""
    name, model = "mock", "extractive-1"

    def stream(self, system, prompt):
        first = next((ln for ln in prompt.splitlines() if ln.startswith("[1]")), "[1] no source found")
        answer = "Based on the sources: " + first[3:].strip().split(". ")[0] + " [1]"
        for word in answer.split(" "):
            yield word + " "
        self.usage = (estimate(system + prompt), estimate(answer), True)


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key, model="claude-sonnet-5-5", transport=None):
        super().__init__()
        self.model = model
        self.client = httpx.Client(base_url="https://api.anthropic.com", transport=transport, timeout=60,
                                   headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})

    def stream(self, system, prompt):
        body = {"model": self.model, "max_tokens": 512, "stream": True, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        in_tok = out_tok = 0
        with self.client.stream("POST", "/v1/messages", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if ev["type"] == "message_start":
                    in_tok = ev["message"]["usage"]["input_tokens"]
                elif ev["type"] == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    yield ev["delta"]["text"]
                elif ev["type"] == "message_delta":
                    out_tok = ev["usage"]["output_tokens"]
        self.usage = (in_tok, out_tok, False)


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key, model="gpt-4o-mini", base_url="https://api.openai.com", transport=None):
        super().__init__()
        self.model = model
        self.client = httpx.Client(base_url=base_url, transport=transport, timeout=60,
                                   headers={"Authorization": f"Bearer {api_key}"})

    def stream(self, system, prompt):
        body = {"model": self.model, "stream": True, "stream_options": {"include_usage": True},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        usage = None
        with self.client.stream("POST", "/v1/chat/completions", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                ev = json.loads(line[6:])
                if ev.get("usage"):
                    usage = ev["usage"]
                for ch in ev.get("choices", []):
                    piece = ch.get("delta", {}).get("content")
                    if piece:
                        yield piece
        self.usage = (usage["prompt_tokens"], usage["completion_tokens"], False) if usage else (0, 0, True)


class BedrockProvider(Provider):
    """Uses the Converse API. Streams the finished answer in word pieces; a ConverseStream variant is a later step."""
    name = "bedrock"

    def __init__(self, model="anthropic.claude-3-5-sonnet-20241022-v2:0", client=None):
        super().__init__()
        self.model = model
        if client is None:
            import boto3
            client = boto3.client("bedrock-runtime")
        self.client = client

    def stream(self, system, prompt):
        r = self.client.converse(modelId=self.model, system=[{"text": system}],
                                 messages=[{"role": "user", "content": [{"text": prompt}]}],
                                 inferenceConfig={"maxTokens": 512})
        text = r["output"]["message"]["content"][0]["text"]
        for word in text.split(" "):
            yield word + " "
        u = r["usage"]
        self.usage = (u["inputTokens"], u["outputTokens"], False)


def build(name, env):
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        return AnthropicProvider(env["ANTHROPIC_API_KEY"])
    if name == "openai":
        return OpenAIProvider(env["OPENAI_API_KEY"])
    if name == "bedrock":
        return BedrockProvider()
    raise ValueError(f"unknown provider {name}")
