(function () {
  'use strict';

  if (window.top !== window.self) return;
  if (document.getElementById('shoaib-otp-float-root')) return;

  const DEFAULT_API = 'http://127.0.0.1:8500';
  let apiUrl = DEFAULT_API;
  const currentBot = '@Dark_Panel_83_bot';
  let nextKeyword = '';
  let latestMsg = null;
  let isOpen = false;
  let polling = true;
  let pollTimer = null;
  let loading = false;
  const isDarkPanel = () => currentBot.replace(/^@/, '').toLowerCase() === 'dark_panel_83_bot';
  const sessionFreshPhones = new Set();

  const root = document.createElement('div');
  root.id = 'shoaib-otp-float-root';
  root.innerHTML = `
    <div class="otp-fab" id="otp-fab-btn" role="button" tabindex="0" aria-label="Open OTP panel" aria-expanded="false" title="Open OTP panel (drag to move)">+</div>
    <div class="otp-card otp-f-hidden" id="otp-float-card">
      <div class="otp-hdr" id="otp-drag-hdr">
        <span class="otp-hdr-title">OTP Bot <span id="otp-f-status" class="otp-f-badge">...</span></span>
        <div class="otp-hdr-actions">
          <button type="button" class="otp-mini-btn" id="otp-f-gear" title="Server URL">⚙</button>
          <button type="button" class="otp-mini-btn" id="otp-f-min" aria-label="Minimize OTP panel" title="Minimize">−</button>
          <button type="button" class="otp-mini-btn" id="otp-f-close" aria-label="Hide OTP panel" title="Close">✕</button>
        </div>
      </div>

      <!-- Settings URL Box -->
      <div id="otp-f-settings" class="otp-f-box otp-f-hidden">
        <input id="otp-f-token" class="otp-f-inp" type="password" placeholder="Server access token" autocomplete="off" />
        <div style="font-size:11px;color:#a1a1aa;margin-bottom:4px;">Render / Local Server URL:</div>
        <div class="otp-f-row" style="margin-bottom:0;">
          <input id="otp-f-url-inp" class="otp-f-inp" type="text" placeholder="https://otp-bot.onrender.com" />
          <button type="button" class="otp-mini-btn primary" id="otp-f-url-save">Save</button>
        </div>
      </div>

      <!-- Login Box -->
      <div id="otp-f-login" class="otp-f-box otp-f-hidden">
        <div class="otp-f-row">
          <input id="otp-f-phone" class="otp-f-inp" type="text" placeholder="+91..." />
          <button type="button" class="otp-mini-btn primary" id="otp-f-send-code">OTP</button>
        </div>
        <div id="otp-f-code-row" class="otp-f-row otp-f-hidden">
          <input id="otp-f-code" class="otp-f-inp" type="text" placeholder="Code" />
          <input id="otp-f-pass" class="otp-f-inp otp-f-hidden" type="password" placeholder="2FA" />
          <button type="button" class="otp-mini-btn primary" id="otp-f-signin">Login</button>
        </div>
        <div id="otp-f-login-err" style="color:#f87171;font-size:11px;"></div>
      </div>

      <!-- Main Bot Box -->
      <div id="otp-f-main" class="otp-f-hidden">
        <div class="otp-f-row">
          <span>@Dark_Panel_83_bot</span>
        </div>

        <div class="otp-f-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="font-size:11px;color:#a1a1aa;">Number</span>
            <span id="otp-f-num-badge" class="otp-f-badge">Waiting</span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
            <span class="otp-f-num" id="otp-f-cur-num">----------</span>
            <button type="button" class="otp-mini-btn primary" id="otp-f-copy-num">Copy</button>
          </div>
        </div>

        <div class="otp-f-row">
          <input id="otp-f-next-kw" class="otp-f-inp" type="text" placeholder="Next btn (e.g. Next)" />
          <button type="button" class="otp-mini-btn primary" id="otp-f-find-fresh">Find Fresh</button>
        </div>
        <div id="otp-f-fresh-msg" style="font-size:11px;color:#a1a1aa;margin-bottom:6px;"></div>
        <div id="otp-f-auto-controls" class="otp-f-row otp-f-hidden">
          <button type="button" class="otp-mini-btn primary" id="otp-f-new-number">Find Number</button>
          <button type="button" class="otp-mini-btn" id="otp-f-stop">Stop</button>
        </div>

        <div class="otp-f-box">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:11px;color:#a1a1aa;">Live OTP (3s)</span>
            <button type="button" class="otp-mini-btn" id="otp-f-poll-btn" style="padding:2px 6px;font-size:10px;">Pause</button>
          </div>
          <div id="otp-f-otp-list" style="font-size:11px;color:#71717a;margin-top:4px;">Waiting for OTP...</div>
        </div>

        <div id="otp-f-bot-btns" class="otp-f-bot-btns"></div>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  const fab = root.querySelector('#otp-fab-btn');
  const card = root.querySelector('#otp-float-card');
  const dragHdr = root.querySelector('#otp-drag-hdr');
  function clampPosition() {
    const rect = root.getBoundingClientRect();
    root.style.left = Math.max(4, Math.min(rect.left, window.innerWidth - rect.width - 4)) + 'px';
    root.style.top = Math.max(4, Math.min(rect.top, window.innerHeight - rect.height - 4)) + 'px';
    root.style.right = 'auto';
  }
  window.addEventListener('resize', clampPosition);

  chrome.storage.local.get(['otpApiUrl', 'otpNextKw', 'otpPos', 'otpAccessToken'], (res) => {
    root.querySelector('#otp-f-token').value = res.otpAccessToken || '';
    if (res.otpApiUrl) apiUrl = res.otpApiUrl;
    if (res.otpNextKw) {
      nextKeyword = res.otpNextKw;
      root.querySelector('#otp-f-next-kw').value = nextKeyword;
    }
    root.querySelector('#otp-f-url-inp').value = apiUrl;
    if (res.otpPos && typeof res.otpPos.left === 'number') {
      root.style.left = res.otpPos.left + 'px';
      root.style.top = res.otpPos.top + 'px';
      root.style.right = 'auto';
    }
  });

  function makeDraggable(handle, onTap) {
    let dragging = false;
    let startX = 0, startY = 0, initL = 0, initT = 0;

    function start(cx, cy) {
      dragging = false;
      startX = cx;
      startY = cy;
      const r = root.getBoundingClientRect();
      initL = r.left;
      initT = r.top;
    }

    function move(cx, cy) {
      const dx = cx - startX;
      const dy = cy - startY;
      if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
        dragging = true;
        const maxX = window.innerWidth - root.getBoundingClientRect().width - 4;
        const maxY = window.innerHeight - root.getBoundingClientRect().height - 4;
        const newL = Math.max(4, Math.min(maxX, initL + dx));
        const newT = Math.max(4, Math.min(maxY, initT + dy));
        root.style.left = newL + 'px';
        root.style.top = newT + 'px';
        root.style.right = 'auto';
      }
    }

    function end() {
      if (dragging) {
        const r = root.getBoundingClientRect();
        chrome.storage.local.set({ otpPos: { left: r.left, top: r.top } });
      } else if (onTap) {
        onTap();
      }
    }

    handle.addEventListener('touchstart', (e) => {
      if (e.target.closest('button')) return;
      const t = e.touches[0];
      start(t.clientX, t.clientY);
    }, { passive: true });

    handle.addEventListener('touchmove', (e) => {
      if (e.target.closest('button')) return;
      const t = e.touches[0];
      move(t.clientX, t.clientY);
      if (dragging) e.preventDefault();
    }, { passive: false });

    handle.addEventListener('touchend', (e) => {
      if (e.target.closest('button')) return;
      end();
    });

    handle.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) return;
      start(e.clientX, e.clientY);
      const onMM = (ev) => move(ev.clientX, ev.clientY);
      const onMU = () => {
        document.removeEventListener('mousemove', onMM);
        document.removeEventListener('mouseup', onMU);
        end();
      };
      document.addEventListener('mousemove', onMM);
      document.addEventListener('mouseup', onMU);
    });
  }

  makeDraggable(fab, () => {
    isOpen = true;
    fab.setAttribute('aria-expanded', 'true');
    fab.classList.add('otp-f-hidden');
    card.classList.remove('otp-f-hidden');
    clampPosition();
    checkAuth();
  });
  makeDraggable(dragHdr, null);

  root.querySelector('#otp-f-min').addEventListener('click', () => {
    isOpen = false;
    fab.setAttribute('aria-expanded', 'false');
    card.classList.add('otp-f-hidden');
    fab.classList.remove('otp-f-hidden');
  });

  root.querySelector('#otp-f-close').addEventListener('click', () => {
    isOpen = false;
    polling = false;
    if (pollTimer) clearInterval(pollTimer);
    root.style.display = 'none';
  });

  root.querySelector('#otp-f-gear').addEventListener('click', () => {
    root.querySelector('#otp-f-settings').classList.toggle('otp-f-hidden');
  });

  root.querySelector('#otp-f-url-save').addEventListener('click', async () => {
    let val = root.querySelector('#otp-f-url-inp').value.trim().replace(/\/+$/, '');
    if (!val) val = DEFAULT_API;
    apiUrl = val;
    await chrome.storage.local.set({ otpApiUrl: apiUrl, otpAccessToken: root.querySelector('#otp-f-token').value.trim() });
    root.querySelector('#otp-f-settings').classList.add('otp-f-hidden');
    checkAuth();
  });

  async function api(path, method = 'GET', body = null) {
    const response = await chrome.runtime.sendMessage({ type: 'otp-api', path, method, body });
    if (!response || response.error) throw new Error(response?.error || 'Extension connection lost. Reload this page.');
    return response.result;
  }

  async function checkAuth() {
    const stBadge = root.querySelector('#otp-f-status');
    stBadge.textContent = 'Waking up...';
    stBadge.className = 'otp-f-badge wake';
    try {
      const st = await api('/api/auth/status');
      if (st.authorized) {
        stBadge.textContent = `+${st.user.phone}`;
        stBadge.className = 'otp-f-badge fresh';
        root.querySelector('#otp-f-login').classList.add('otp-f-hidden');
        root.querySelector('#otp-f-main').classList.remove('otp-f-hidden');
        await loadMessages();
        startPolling();
      } else {
        stBadge.textContent = 'Login';
        stBadge.className = 'otp-f-badge dup';
        root.querySelector('#otp-f-login').classList.remove('otp-f-hidden');
        root.querySelector('#otp-f-main').classList.add('otp-f-hidden');
      }
    } catch (e) {
      stBadge.textContent = 'Sleeping / Retry...';
      root.querySelector('#otp-f-settings').classList.remove('otp-f-hidden');
      root.querySelector('#otp-f-login-err').textContent = e.message;
      stBadge.title = e.message;
      stBadge.className = 'otp-f-badge wake';
      if (isOpen) {
        setTimeout(() => { if (isOpen) checkAuth(); }, 4000);
      }
    }
  }

  root.querySelector('#otp-f-send-code').addEventListener('click', async () => {
    const phone = root.querySelector('#otp-f-phone').value.trim();
    const err = root.querySelector('#otp-f-login-err');
    err.textContent = '';
    try {
      const res = await api('/api/auth/send_code', 'POST', { phone });
      if (res.ok) root.querySelector('#otp-f-code-row').classList.remove('otp-f-hidden');
      else err.textContent = res.error;
    } catch (e) { err.textContent = 'Server unreachable'; }
  });

  root.querySelector('#otp-f-signin').addEventListener('click', async () => {
    const code = root.querySelector('#otp-f-code').value.trim();
    const password = root.querySelector('#otp-f-pass').value.trim();
    const err = root.querySelector('#otp-f-login-err');
    err.textContent = '';
    const res = await api('/api/auth/sign_in', 'POST', { code, password });
    if (res.ok) checkAuth();
    else {
      if (res.need_password) root.querySelector('#otp-f-pass').classList.remove('otp-f-hidden');
      err.textContent = res.error;
    }
  });

  async function loadMessages() {
    const dark = isDarkPanel();
    root.querySelector('#otp-f-auto-controls').classList.toggle('otp-f-hidden', !dark);
    root.querySelector('#otp-f-next-kw').parentElement.classList.toggle('otp-f-hidden', dark);
    root.querySelector('#otp-f-poll-btn').classList.toggle('otp-f-hidden', dark);
    if (!currentBot || loading) return;
    loading = true;
    try {
      if (dark) {
        const state = await api('/api/dark-panel');
        if (isDarkPanel()) renderAutomation(state);
        return;
      }
      const res = await api(`/api/bot/messages?bot=${encodeURIComponent(currentBot)}`);
      if (res.ok && !isDarkPanel()) renderMessages(res.messages);
    } catch (e) { root.querySelector('#otp-f-fresh-msg').textContent = e.message; }
    finally { loading = false; }
  }

  function renderAutomation(state) {
    latestMsg = { phone: state.phone };
    root.querySelector('#otp-f-cur-num').textContent = state.phone || '----------';
    const badge = root.querySelector('#otp-f-num-badge');
    badge.textContent = state.phone ? `FRESH · ${state.remaining || 0}s` : state.phase;
    badge.className = 'otp-f-badge' + (state.phone ? ' fresh' : '');
    root.querySelector('#otp-f-fresh-msg').textContent = state.error ||
      `${state.phase}${state.panel ? ` · Panel ${state.panel}/${state.panels}` : ''}. ${state.last_result || ''}`;
    root.querySelector('#otp-f-stop').disabled = !state.running;
    root.querySelector('#otp-f-bot-btns').replaceChildren();
    const list = root.querySelector('#otp-f-otp-list');
    list.replaceChildren();
    for (const item of (state.history || []).filter(item => item.phone === state.phone)) {
      const row = document.createElement('div');
      row.className = 'otp-f-otp-row';
      const label = document.createElement('span');
      label.textContent = `${item.phone} → ${item.code}`;
      const copy = document.createElement('button');
      copy.className = 'otp-mini-btn primary';
      copy.textContent = 'Copy OTP';
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(item.code); copy.textContent = 'Copied!'; }
        catch (_) { copy.textContent = 'Copy failed'; }
      };
      row.append(label, copy);
      list.appendChild(row);
    }
    if (!list.childNodes.length) list.textContent = 'Waiting for a new OTP (old SMS ignored).';
  }

  for (const [id, action] of [['otp-f-new-number', 'start'], ['otp-f-stop', 'stop']]) {
    root.querySelector('#' + id).addEventListener('click', async (event) => {
      event.target.disabled = true;
      try { renderAutomation(await api('/api/dark-panel', 'POST', { action })); }
      catch (error) { root.querySelector('#otp-f-fresh-msg').textContent = error.message; }
      finally { event.target.disabled = false; }
    });
  }

  function renderMessages(messages) {
    if (!messages || !messages.length) return;
    const target = messages.find(m => m.phone || (m.buttons && m.buttons.length > 0)) || messages[0];
    latestMsg = target;

    const numEl = root.querySelector('#otp-f-cur-num');
    const badgeEl = root.querySelector('#otp-f-num-badge');
    if (target.phone) {
      numEl.textContent = target.phone;
      if (target.auto_saved) {
        sessionFreshPhones.add(target.phone);
      }
      if (sessionFreshPhones.has(target.phone) || !target.is_duplicate) {
        badgeEl.textContent = 'FRESH (SAVED)';
        badgeEl.className = 'otp-f-badge fresh';
      } else {
        badgeEl.textContent = 'DUPLICATE';
        badgeEl.className = 'otp-f-badge dup';
      }
    } else {
      numEl.textContent = '----------';
      badgeEl.textContent = 'Waiting';
      badgeEl.className = 'otp-f-badge';
    }

    const allOtps = [];
    for (const m of messages) {
      if (m.otps) {
        for (const o of m.otps) {
          if (!allOtps.some(x => x.code === o.code)) allOtps.push(o);
        }
      }
    }
    const otpList = root.querySelector('#otp-f-otp-list');
    if (allOtps.length > 0) {
      otpList.innerHTML = allOtps.map(o => `
        <div class="otp-f-otp-row">
          <span class="otp-f-code">${o.code}</span>
          <button type="button" class="otp-mini-btn primary" data-copy="${o.code}">Copy</button>
        </div>
      `).join('');
      otpList.querySelectorAll('[data-copy]').forEach(btn => {
        btn.addEventListener('click', () => {
          navigator.clipboard.writeText(btn.getAttribute('data-copy'));
          btn.textContent = 'Copied!';
          setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
        });
      });
    } else {
      otpList.textContent = 'Waiting for OTP (3s polling)...';
    }

    const btnsEl = root.querySelector('#otp-f-bot-btns');
    btnsEl.innerHTML = '';
    if (target.buttons) {
      for (const row of target.buttons) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'otp-f-btn-row';
        for (const btn of row) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'otp-mini-btn';
          b.textContent = btn.text;
          b.addEventListener('click', async () => {
            const otp = btn.text.match(/Copy\s*OTP\s*:\s*(\d{4,8})\b/i);
            if (otp) {
              try { await navigator.clipboard.writeText(otp[1]); b.textContent = 'Copied!'; }
              catch (_) { b.textContent = 'Copy failed'; }
              return;
            }
            const r = await api('/api/bot/click', 'POST', {
              bot: currentBot, msg_id: target.id, row: btn.row, col: btn.col
            });
            if (r.ok) renderMessages(r.messages);
          });
          rowDiv.appendChild(b);
        }
        btnsEl.appendChild(rowDiv);
      }
    }
  }

  root.querySelector('#otp-f-copy-num').addEventListener('click', async () => {
    if (latestMsg && latestMsg.phone) {
      const b = root.querySelector('#otp-f-copy-num');
      try { await navigator.clipboard.writeText(latestMsg.phone); b.textContent = 'Copied!'; }
      catch (_) { b.textContent = 'Copy failed'; }
      setTimeout(() => { b.textContent = 'Copy'; }, 1200);
    }
  });

  root.querySelector('#otp-f-find-fresh').addEventListener('click', async () => {
    const kw = root.querySelector('#otp-f-next-kw').value.trim();
    if (!currentBot || !kw) return;
    chrome.storage.local.set({ otpNextKw: kw });
    const btn = root.querySelector('#otp-f-find-fresh');
    const st = root.querySelector('#otp-f-fresh-msg');
    btn.disabled = true;
    st.textContent = 'Finding fresh number...';
    try {
      const res = await api('/api/bot/find_fresh', 'POST', {
        bot: currentBot, button_text: kw, max_tries: 12
      });
      if (res.ok) {
        renderMessages(res.messages);
        st.textContent = res.found_fresh
          ? `Fresh found & saved (${res.attempts} tries)`
          : `All ${res.attempts} were duplicate`;
      } else {
        st.textContent = res.error;
      }
    } finally {
      btn.disabled = false;
    }
  });

  root.querySelector('#otp-f-poll-btn').addEventListener('click', (e) => {
    polling = !polling;
    e.target.textContent = polling ? 'Pause' : 'Resume';
  });

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (isOpen && (polling || isDarkPanel()) && currentBot) loadMessages();
    }, 3000);
  }
})();
