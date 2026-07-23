/* ═══════════════════════════════════════════════════════════════════════════
   Ask-the-SRE Copilot — dashboard chat widget.
   Talks to the backend proxy POST /api/copilot/ask (which forwards to the
   SRE Copilot agent on :8010). Keeps a short client-side history for context.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
    const API = window.location.origin + window.location.pathname.replace(/\/$/, '');
    const history = [];
    let busy = false;

    const $ = (id) => document.getElementById(id);
    const esc = (s) => (window.GPS ? GPS.esc(s) : String(s == null ? '' : s));

    function open() {
        $('copilot-panel').classList.remove('copilot-hidden');
        $('copilot-fab').classList.add('copilot-open');
        setTimeout(() => $('copilot-text').focus(), 50);
        if (!$('copilot-messages').children.length) {
            addBot("Hi — I'm your SRE copilot. Ask me about recent errors, a specific "
                + "credit application, error-rate trends, or what a runbook says. "
                + "I answer using live audit_log data, runbooks and incident history.");
        }
    }
    function close() {
        $('copilot-panel').classList.add('copilot-hidden');
        $('copilot-fab').classList.remove('copilot-open');
    }

    function addMsg(role, html, extraClass) {
        const wrap = document.createElement('div');
        wrap.className = `copilot-msg ${role}${extraClass ? ' ' + extraClass : ''}`;
        wrap.innerHTML = html;
        const box = $('copilot-messages');
        box.appendChild(wrap);
        box.scrollTop = box.scrollHeight;
        return wrap;
    }
    function addUser(text) { addMsg('user', esc(text)); }
    function addBot(text) { addMsg('bot', formatAnswer(text)); }

    // Minimal, safe formatting: escape first, then turn blank lines into <br>
    // and leading "- " / "* " into bullet rows.
    function formatAnswer(text) {
        const safe = esc(text);
        const lines = safe.split('\n');
        let out = '', inList = false;
        for (const raw of lines) {
            const line = raw.trimEnd();
            if (/^\s*[-*]\s+/.test(line)) {
                if (!inList) { out += '<ul>'; inList = true; }
                out += `<li>${line.replace(/^\s*[-*]\s+/, '')}</li>`;
            } else {
                if (inList) { out += '</ul>'; inList = false; }
                out += line ? `<p>${line}</p>` : '';
            }
        }
        if (inList) out += '</ul>';
        return out || `<p>${safe}</p>`;
    }

    function typing(on) {
        let el = $('copilot-typing');
        if (on) {
            if (!el) {
                el = addMsg('bot', '<span class="copilot-dots"><i></i><i></i><i></i></span>', 'typing');
                el.id = 'copilot-typing';
            }
        } else if (el) {
            el.remove();
        }
    }

    async function ask(question) {
        if (busy || !question.trim()) return;
        busy = true;
        $('copilot-send').disabled = true;
        addUser(question);
        history.push({ role: 'user', content: question });
        $('copilot-suggest').style.display = 'none';
        typing(true);

        let data = null;
        try {
            const r = await fetch(`${API}/api/copilot/ask`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, history: history.slice(-6) }),
            });
            data = await r.json();
        } catch (e) {
            data = { error: 'Could not reach the copilot service.' };
        }
        typing(false);

        if (data && data.answer) {
            addBot(data.answer);
            history.push({ role: 'assistant', content: data.answer });
            const chips = [];
            if (Array.isArray(data.sources) && data.sources.length)
                chips.push(`sources: ${data.sources.join(', ')}`);
            if (data.sql_used) chips.push('ran SQL');
            if (chips.length) {
                addMsg('bot', chips.map(c => `<span class="copilot-tag">${esc(c)}</span>`).join(''), 'meta');
            }
        } else {
            addBot(`⚠️ ${(data && (data.error || data.detail)) || 'Something went wrong.'}`);
        }

        busy = false;
        $('copilot-send').disabled = false;
        $('copilot-text').focus();
    }

    function init() {
        $('copilot-fab').addEventListener('click', () =>
            $('copilot-panel').classList.contains('copilot-hidden') ? open() : close());
        $('copilot-close').addEventListener('click', close);
        $('copilot-form').addEventListener('submit', (e) => {
            e.preventDefault();
            const t = $('copilot-text');
            const q = t.value;
            t.value = '';
            ask(q);
        });
        document.querySelectorAll('#copilot-suggest .copilot-chip').forEach(btn =>
            btn.addEventListener('click', () => ask(btn.textContent)));
    }

    if (document.readyState === 'loading')
        document.addEventListener('DOMContentLoaded', init);
    else init();
})();
