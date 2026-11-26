chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message.type !== 'otp-api') return;
  (async () => {
    const settings = await chrome.storage.local.get(['otpApiUrl', 'otpAccessToken']);
    const base = (settings.otpApiUrl || 'http://127.0.0.1:8500').replace(/\/+$/, '');
    const url = new URL(base);
    if (!['http:', 'https:'].includes(url.protocol) || !message.path.startsWith('/api/')) {
      throw new Error('Invalid server URL or API path');
    }
    const response = await fetch(base + message.path, {
      method: message.method || 'GET',
      headers: { 'Content-Type': 'application/json',
        ...(settings.otpAccessToken ? { Authorization: `Bearer ${settings.otpAccessToken}` } : {}) },
      body: message.body ? JSON.stringify(message.body) : undefined,
      signal: AbortSignal.timeout(60000)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Server error ${response.status}`);
    reply({ result });
  })().catch(error => reply({ error: error.message }));
  return true;
});
