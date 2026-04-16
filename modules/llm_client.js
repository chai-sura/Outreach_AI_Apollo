/**
 * Minimal LLM client with pluggable providers.
 *
 * Providers:
 * - Ollama (local, free): https://ollama.com
 * - OpenAI (optional fallback)
 */

function getEnv(name) {
  return typeof process !== 'undefined' ? process.env?.[name] : undefined;
}

function getProvider() {
  return (getEnv('LLM_PROVIDER') || 'ollama').toLowerCase();
}

function safeJsonOnlyPrompt(userPrompt) {
  // Keeps behavior consistent across providers that don't have strict JSON modes.
  return `${userPrompt}\n\nIMPORTANT: Respond with ONLY a single valid JSON object. No markdown. No code fences. No extra text.`;
}

async function callOllamaChat({ prompt }) {
  const baseUrl = getEnv('OLLAMA_BASE_URL') || 'http://localhost:11434';
  const model = getEnv('OLLAMA_MODEL') || 'llama3.1:8b';

  const res = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      stream: false,
      messages: [
        {
          role: 'user',
          content: safeJsonOnlyPrompt(prompt),
        },
      ],
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      err?.error ||
      err?.message ||
      `Ollama API error: ${res.status} ${res.statusText}`;
    throw new Error(msg);
  }

  const data = await res.json();
  const text = data?.message?.content;
  if (!text) throw new Error('Ollama returned empty response');
  return text;
}

async function callOpenAIChat({ prompt }) {
  // Prefer Groq if configured, otherwise fall back to OpenAI-style keys.
  const apiKey =
    getEnv('GROQ_API_KEY') ||
    getEnv('API_KEY_PROFILE_EXTRACTOR') ||
    getEnv('OPENAI_API_KEY');

  if (!apiKey) {
    throw new Error(
      'Missing API key. Set GROQ_API_KEY, or API_KEY_PROFILE_EXTRACTOR / OPENAI_API_KEY in your environment.'
    );
  }

  // Allow overriding the base; default to Groq if GROQ_API_KEY is present, else OpenAI.
  const baseUrl =
    getEnv('OPENAI_BASE_URL') ||
    (getEnv('GROQ_API_KEY')
      ? 'https://api.groq.com/openai'
      : 'https://api.openai.com');

  const model =
    getEnv('OPENAI_MODEL') || getEnv('GROQ_MODEL') || 'llama-3.3-70b-versatile';

  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.1,
      max_tokens: 1500,
      response_format: { type: 'json_object' },
      messages: [{ role: 'user', content: prompt }],
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `OpenAI API error: ${res.status}`);
  }

  const data = await res.json();
  const text = data?.choices?.[0]?.message?.content;
  if (!text) throw new Error('OpenAI returned empty response');
  return text;
}

export async function llmGenerateJson({ prompt }) {
  const provider = getProvider();
  if (provider === 'openai') return await callOpenAIChat({ prompt });
  if (provider === 'ollama') return await callOllamaChat({ prompt });
  throw new Error(`Unsupported LLM_PROVIDER: ${provider}`);
}

