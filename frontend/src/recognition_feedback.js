/** Visible progress while waiting; no speculative or automatic provider retries. */
export function startRecognitionProgress(show, current, label) {
  const started = Date.now();
  show(`${label}…`);
  const timer = setInterval(() => {
    if (!current()) { clearInterval(timer); return; }
    const seconds = Math.floor((Date.now() - started) / 1000);
    show(`${label}… ${seconds}s elapsed.${seconds >= 20 ? ' Still waiting for Gemini; you can cancel.' : ''}`);
  }, 1000);
  return () => clearInterval(timer);
}

export async function readRecognitionResponse(response) {
  const data = await response.json().catch(() => {
    throw new Error(response.ok ? 'The AI service returned invalid JSON. Please retry.' : `The AI service returned HTTP ${response.status} without a readable response. Please retry.`);
  });
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : `Recognition failed (HTTP ${response.status}). Please retry.`);
    error.code = data?.code;
    throw error;
  }
  return data;
}
