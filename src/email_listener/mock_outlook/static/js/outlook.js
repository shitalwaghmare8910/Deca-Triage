/* Mock Outlook — inbox UI logic */
(function () {
    "use strict";

    const listEl = document.getElementById("message-list");
    const emptyEl = document.getElementById("list-empty");
    const unreadCountEl = document.getElementById("unread-count");
    const mailboxLabel = document.getElementById("mailbox-label");
    const searchEl = document.getElementById("ol-search");

    const readingEmpty = document.getElementById("reading-empty");
    const readingContent = document.getElementById("reading-content");

    const composeModal = document.getElementById("compose-modal");
    const composeForm = document.getElementById("compose-form");
    const composeMsg = document.getElementById("compose-msg");

    let allMessages = [];
    let selectedId = null;
    let refreshTimer = null;

    function initials(email) {
        const name = (email || "?").split("@")[0];
        return (name[0] || "?").toUpperCase();
    }

    function fmtDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (isNaN(d)) return iso;
        const now = new Date();
        const sameDay = d.toDateString() === now.toDateString();
        return sameDay
            ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : d.toLocaleDateString([], { month: "short", day: "numeric" });
    }

    function esc(s) {
        const div = document.createElement("div");
        div.textContent = s == null ? "" : String(s);
        return div.innerHTML;
    }

    async function loadMessages() {
        try {
            const res = await fetch("api/messages");
            const data = await res.json();
            allMessages = data.result || [];
            if (data.mailbox) mailboxLabel.textContent = data.mailbox;
            render();
        } catch (e) {
            console.error("Failed to load messages", e);
        }
    }

    function render() {
        const q = (searchEl.value || "").toLowerCase();
        const filtered = allMessages.filter((m) => {
            if (!q) return true;
            return (
                (m.subject || "").toLowerCase().includes(q) ||
                (m.bodyPreview || "").toLowerCase().includes(q) ||
                (senderOf(m)).toLowerCase().includes(q)
            );
        });

        const unread = allMessages.filter((m) => !m.isRead).length;
        unreadCountEl.textContent = unread;
        unreadCountEl.style.display = unread ? "" : "none";

        // Preserve reading pane; rebuild list.
        listEl.querySelectorAll(".ol-message").forEach((n) => n.remove());
        emptyEl.style.display = filtered.length ? "none" : "flex";

        for (const m of filtered) {
            listEl.appendChild(rowFor(m));
        }
    }

    function senderOf(m) {
        return (m.from && m.from.emailAddress && m.from.emailAddress.address) || "unknown";
    }

    function rowFor(m) {
        const row = document.createElement("div");
        row.className = "ol-message" + (m.isRead ? "" : " unread") + (m.id === selectedId ? " selected" : "");
        const sender = senderOf(m);
        const badge = m.isReport ? '<span class="ol-report-badge">Report</span>' : "";
        const clip = (m.attachments && m.attachments.length)
            ? '<span class="material-icons-outlined ol-msg-clip">attach_file</span>' : "";
        row.innerHTML = `
            <div class="ol-msg-avatar">${esc(initials(sender))}</div>
            <div class="ol-msg-main">
                <div class="ol-msg-row">
                    <span class="ol-msg-from">${esc(sender)}</span>
                    <span class="ol-msg-date">${clip}${esc(fmtDate(m.receivedDateTime))}</span>
                </div>
                <div class="ol-msg-subject">${badge}${esc(m.subject)}</div>
                <div class="ol-msg-preview">${esc(m.bodyPreview || "")}</div>
            </div>
            <button class="ol-icon-btn ol-msg-delete" title="Delete"><span class="material-icons-outlined">delete_outline</span></button>
        `;
        row.addEventListener("click", (ev) => {
            if (ev.target.closest(".ol-msg-delete")) {
                ev.stopPropagation();
                deleteMessage(m.id);
                return;
            }
            openMessage(m);
        });
        return row;
    }

    function fmtSize(bytes) {
        if (!bytes) return "";
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / 1024 / 1024).toFixed(1) + " MB";
    }

    function renderAttachments(m) {
        const wrap = document.getElementById("read-attachments");
        const atts = (m && m.attachments) || [];
        if (!atts.length) {
            wrap.style.display = "none";
            wrap.innerHTML = "";
            return;
        }
        wrap.innerHTML = "";
        atts.forEach((a, i) => {
            const size = fmtSize(a.size);
            const chip = document.createElement("a");
            chip.className = "ol-attachment-chip";
            chip.href = `api/messages/${m.id}/attachments/${i}`;
            chip.setAttribute("target", "_blank");
            chip.setAttribute("rel", "noopener");
            chip.innerHTML = `
                <span class="material-icons-outlined ol-att-icon">picture_as_pdf</span>
                <span class="ol-att-info">
                    <span class="ol-att-name">${esc(a.name || "attachment")}</span>
                    <span class="ol-att-meta">${esc(size)}</span>
                </span>
                <span class="material-icons-outlined ol-att-dl">download</span>`;
            wrap.appendChild(chip);
        });
        wrap.style.display = "flex";
    }

    function openMessage(m) {
        selectedId = m.id;
        readingEmpty.style.display = "none";
        readingContent.style.display = "block";

        const sender = senderOf(m);
        document.getElementById("read-subject").textContent = m.subject || "(no subject)";
        document.getElementById("read-avatar").textContent = initials(sender);
        document.getElementById("read-from").textContent = sender;
        document.getElementById("read-date").textContent = new Date(m.receivedDateTime).toLocaleString();
        const status = document.getElementById("read-status");
        status.textContent = m.isReport ? "Report" : (m.isRead ? "Read" : "Unread");
        status.className = "ol-read-status" + (m.isReport ? " report" : (m.isRead ? "" : " unread"));

        renderAttachments(m);

        const bodyEl = document.getElementById("read-body");
        const isHtml = m.body && m.body.contentType === "html" && m.body.content;
        if (m.isReport && isHtml) {
            // Render the report HTML in a sandboxed iframe (no scripts, isolated
            // origin) so untrusted analysis content cannot execute.
            bodyEl.innerHTML = "";
            const frame = document.createElement("iframe");
            frame.className = "ol-report-frame";
            frame.setAttribute("sandbox", "");
            frame.srcdoc = m.body.content;
            bodyEl.appendChild(frame);
        } else {
            const bodyContent = (m.body && m.body.content) || m.bodyPreview || "(no content)";
            bodyEl.textContent = bodyContent;
        }

        // Reflect selection styling without a full reload.
        render();
    }

    async function deleteMessage(id) {
        try {
            await fetch(`api/messages/${id}`, { method: "DELETE" });
            if (selectedId === id) {
                selectedId = null;
                readingContent.style.display = "none";
                readingEmpty.style.display = "flex";
            }
            loadMessages();
        } catch (e) {
            console.error("Delete failed", e);
        }
    }

    // Compose modal
    function openCompose() {
        composeMsg.textContent = "";
        composeModal.style.display = "flex";
        document.getElementById("c-subject").focus();
    }
    function closeCompose() {
        composeModal.style.display = "none";
        composeForm.reset();
        document.getElementById("c-from").value = "monitoring@alerts.local";
    }

    composeForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const payload = {
            from: document.getElementById("c-from").value.trim(),
            subject: document.getElementById("c-subject").value.trim(),
            body: document.getElementById("c-body").value.trim(),
        };
        try {
            const res = await fetch("api/compose", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                composeMsg.style.color = "#a4262c";
                composeMsg.textContent = err.error || "Failed to send";
                return;
            }
            composeMsg.style.color = "#107c10";
            composeMsg.textContent = "Alert delivered to inbox.";
            await loadMessages();
            setTimeout(closeCompose, 700);
        } catch (e) {
            composeMsg.style.color = "#a4262c";
            composeMsg.textContent = "Network error";
        }
    });

    document.getElementById("btn-new-mail").addEventListener("click", openCompose);
    document.getElementById("btn-close-compose").addEventListener("click", closeCompose);
    document.getElementById("btn-cancel-compose").addEventListener("click", closeCompose);
    composeModal.addEventListener("click", (ev) => { if (ev.target === composeModal) closeCompose(); });
    document.getElementById("btn-refresh").addEventListener("click", loadMessages);
    searchEl.addEventListener("input", render);

    // Initial load + gentle auto-refresh so the listener marking mail as read
    // (isRead=true) shows up in the UI.
    loadMessages();
    refreshTimer = setInterval(loadMessages, 5000);
    window.addEventListener("beforeunload", () => clearInterval(refreshTimer));
})();
