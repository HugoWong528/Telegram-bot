# Pollinations AI — API Reference

This bot uses the [Pollinations AI](https://pollinations.ai) API for all AI responses.  
The API is free to use with a token from <https://enter.pollinations.ai>.

---

## Chat Completions Endpoint

**POST** `https://gen.pollinations.ai/v1/chat/completions`

### Headers

```
Authorization: Bearer <POLLINATIONS_TOKEN>
Content-Type: application/json
```

### Request body

```json
{
  "model": "openai-fast",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user",   "content": "Hello!"}
  ],
  "stream": false
}
```

Set `"stream": true` to receive Server-Sent Events (SSE).

### Response (non-streaming)

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      }
    }
  ]
}
```

### Response (streaming SSE)

Each event looks like:

```
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: {"choices":[{"delta":{"content":"!"}}]}
data: [DONE]
```

---

## Available Models

| Model | Vision | Notes |
|---|:---:|---|
| `openai-fast` | ✅ | Fast OpenAI model — default first choice |
| `openai` | ✅ | Full OpenAI model |
| `gemini-search` | ✅ | Gemini with Google Search grounding |
| `gemini` | ✅ | Standard Gemini model |
| `gemini-fast` | ✅ | Faster Gemini variant |
| `gemini-large` | ✅ | Larger Gemini variant |
| `claude-fast` | ✅ | Fast Claude model |
| `glm` | ❌ | GLM model |
| `qwen-character` | ❌ | Qwen character model |
| `deepseek` | ❌ | DeepSeek model |
| `qwen-safety` | ❌ | Qwen safety-focused model |

Vision models accept `image_url` content items in the message body (see example below).

---

## Vision (Image Input)

For models with vision support, include image URLs in the message content:

```json
{
  "model": "openai-fast",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
      ]
    }
  ]
}
```

---

## Model Fallback Chain

The bot tries models in this order and moves to the next on any error:

```
openai-fast → gemini-search → openai → glm → claude-fast → qwen-character → deepseek → qwen-safety
```

---

## Resources

- **Pollinations AI website:** <https://pollinations.ai>
- **Get a token:** <https://enter.pollinations.ai>
- **API status / announcements:** <https://discord.gg/pollinations>
