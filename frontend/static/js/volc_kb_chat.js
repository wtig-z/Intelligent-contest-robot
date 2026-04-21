/**
 * 火山知识库通道：与 index.html 同款壳（侧栏 / 级联赛事 / 欢迎页 / 输入区），
 * 对话请求走 POST /api/volc_kb/chat（与 /api/chat 独立）。
 */
(function () {
    const un = document.getElementById('username');
    function _hasCookieToken() {
        try {
            return document.cookie.split(';').some(function (c) { return c.trim().startsWith('token='); });
        } catch (e) {
            return false;
        }
    }

    function _isLoggedInForUi() {
        const hasToken = !!localStorage.getItem('token');
        const hasUserId = !!localStorage.getItem('user_id');
        if (hasToken && hasUserId) return true;
        return false;
    }

    if (un) {
        un.textContent = _isLoggedInForUi()
            ? (localStorage.getItem('username') || '用户')
            : '游客';
    }

    (function syncMeToUi() {
        if (!(window.CR && window.CR.Auth && typeof window.CR.Auth.checkAuth === 'function') || !un) return;
        var SI = window.CR.Auth.SESSION_INVALID;
        window.CR.Auth.checkAuth().then(function (me) {
            if (me === SI || (me && me.__sessionInvalid)) {
                if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
                    try { window.CR.Auth.clearAuth(); } catch (e) {}
                }
                un.textContent = '游客';
                try {
                    purgeVolcChatAfterAuthLoss();
                } catch (e2) {}
                return;
            }
            if (me && me.username) {
                try {
                    localStorage.setItem('user_id', String(me.id));
                    localStorage.setItem('is_admin', String(me.role === 'admin'));
                    localStorage.setItem('username', String(me.username));
                } catch (e) {}
                un.textContent = String(me.username);
                return;
            }
            // /me 异常或短暂失败：有 token/cookie 则保留登录态，避免刷新误清空
            if (localStorage.getItem('token') || _hasCookieToken()) {
                un.textContent = localStorage.getItem('username') || '用户';
            } else {
                if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
                    try { window.CR.Auth.clearAuth(); } catch (e) {}
                }
                un.textContent = '游客';
            }
        }).catch(function () {
            if (localStorage.getItem('token') || _hasCookieToken()) {
                un.textContent = localStorage.getItem('username') || '用户';
            } else {
                un.textContent = '游客';
            }
        }).finally(function () {
            if (typeof applyWelcomeHotTagsPolicy === 'function') applyWelcomeHotTagsPolicy();
        });
    })();

    document.getElementById('logout')?.addEventListener('click', function (e) {
        e.preventDefault();
        try {
            clearVolcSession();
        } catch (e2) {}
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') window.CR.Auth.clearAuth();
        else {
            localStorage.removeItem('token');
            localStorage.removeItem('username');
            localStorage.removeItem('user_id');
            localStorage.removeItem('is_admin');
            document.cookie = 'token=; Path=/; Max-Age=0; SameSite=Lax';
        }
        window.location.href = '/login';
    });

    const chatArea = document.getElementById('chatArea');
    const welcome = document.getElementById('welcome');
    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const deepThinkBtn = document.getElementById('deepThinkBtn');
    const deepThinkBtnWelcome = document.getElementById('deepThinkBtnWelcome');
    const inputBar = document.getElementById('inputBar');
    const welcomeInput = document.getElementById('welcomeInput');
    const welcomeSendBtn = document.getElementById('welcomeSendBtn');
    const vkUploadBtnWelcome = document.getElementById('vkUploadBtnWelcome');
    const vkFileInputWelcome = document.getElementById('vkFileInputWelcome');
    const vkPreviewWelcome = document.getElementById('vkPreviewWelcome');
    const vkUploadBtnBar = document.getElementById('vkUploadBtnBar');
    const vkFileInputBar = document.getElementById('vkFileInputBar');
    const vkPreviewBar = document.getElementById('vkPreviewBar');

    if (inputBar) inputBar.style.display = 'none';

    let deepThinkEnabled = true;
    function _syncDeepThinkUi() {
        try { if (deepThinkBtn) deepThinkBtn.classList.toggle('is-active', !!deepThinkEnabled); } catch (e) {}
        try { if (deepThinkBtnWelcome) deepThinkBtnWelcome.classList.toggle('is-active', !!deepThinkEnabled); } catch (e) {}
    }
    function _bindDeepThink(btn) {
        if (!btn) return;
        try { btn.classList.remove('is-active'); } catch (e) {}
        btn.addEventListener('click', function () {
            deepThinkEnabled = !deepThinkEnabled;
            _syncDeepThinkUi();
        });
    }
    _bindDeepThink(deepThinkBtn);
    _bindDeepThink(deepThinkBtnWelcome);
    _syncDeepThinkUi();

    function showLoginTipAndGo() {
        try { sessionStorage.setItem('flash_login_tip', '请先登录！'); } catch (e) {}
        try {
            purgeVolcChatAfterAuthLoss();
        } catch (e2) {}
        window.location.href = '/login?next=' + encodeURIComponent('/volc-kb');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /** 去掉模型偶发的未渲染引用标签，避免正文出现裸 XML */
    function stripVolcRawTags(text) {
        var s = (text == null) ? '' : String(text);
        s = s.replace(/<\s*\/?\s*(?:reference|illustration)\b[^>]*>/gi, '');
        s = s.replace(/<\s*[^>]*$/g, '');
        return s;
    }

    function nl2br(text) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function renderMarkdown(md) {
        md = (md == null) ? '' : String(md);
        const lines = md.replace(/\r\n/g, '\n').split('\n');
        let html = '';
        let inList = false;
        let inTable = false;
        let tableHeader = null;
        let tableRows = [];

        function closeList() {
            if (inList) {
                html += '</ul>';
                inList = false;
            }
        }

        function _isTableRow(t) {
            const s = String(t || '');
            const pipeCount = (s.match(/\|/g) || []).length;
            return pipeCount >= 2;
        }

        function _isTableSepRow(t) {
            const s = String(t || '').trim();
            if (!_isTableRow(s)) return false;
            const inner = s.replace(/^\s*\|/, '').replace(/\|\s*$/, '');
            const cells = inner.split('|').map(function (c) { return c.trim(); }).filter(Boolean);
            if (!cells.length) return false;
            return cells.every(function (c) {
                return /^:?-{2,}:?$/.test(c);
            });
        }

        function _parseTableCells(t) {
            const s = String(t || '').trim();
            const inner = s.replace(/^\s*\|/, '').replace(/\|\s*$/, '');
            return inner.split('|').map(function (c) { return c.trim(); });
        }

        function closeTable() {
            if (!inTable) return;
            const head = Array.isArray(tableHeader) ? tableHeader : null;
            const rows = Array.isArray(tableRows) ? tableRows : [];
            if (head && head.length) {
                html += '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
                for (let i = 0; i < head.length; i++) {
                    html += '<th>' + inlineFormat(head[i]) + '</th>';
                }
                html += '</tr></thead><tbody>';
                for (let r = 0; r < rows.length; r++) {
                    const row = rows[r] || [];
                    html += '<tr>';
                    for (let c = 0; c < head.length; c++) {
                        html += '<td>' + inlineFormat(row[c] == null ? '' : row[c]) + '</td>';
                    }
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            } else if (rows.length) {
                const maxCols = Math.max.apply(null, rows.map(function (r) { return (r || []).length; }));
                html += '<div class="md-table-wrap"><table class="md-table"><tbody>';
                for (let r = 0; r < rows.length; r++) {
                    const row = rows[r] || [];
                    html += '<tr>';
                    for (let c = 0; c < maxCols; c++) {
                        html += '<td>' + inlineFormat(row[c] == null ? '' : row[c]) + '</td>';
                    }
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            }
            inTable = false;
            tableHeader = null;
            tableRows = [];
        }

        function inlineFormat(s) {
            s = escapeHtml(s);
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            return s;
        }

        for (let i = 0; i < lines.length; i++) {
            const raw = lines[i];
            const line = raw.trimEnd();
            const t = line.trim();

            if (!t) {
                closeTable();
                closeList();
                continue;
            }

            if (t.startsWith('# ')) { closeTable(); closeList(); html += '<h1>' + inlineFormat(t.slice(2)) + '</h1>'; continue; }
            if (t.startsWith('#### ')) { closeTable(); closeList(); html += '<h4>' + inlineFormat(t.slice(5)) + '</h4>'; continue; }
            if (t.startsWith('### ')) { closeTable(); closeList(); html += '<h3>' + inlineFormat(t.slice(4)) + '</h3>'; continue; }
            if (t.startsWith('## ')) { closeTable(); closeList(); html += '<h2>' + inlineFormat(t.slice(3)) + '</h2>'; continue; }

            if (t === '---') { closeTable(); closeList(); html += '<hr>'; continue; }

            if (t.startsWith('- ')) {
                closeTable();
                if (!inList) { html += '<ul>'; inList = true; }
                html += '<li>' + inlineFormat(t.slice(2)) + '</li>';
                continue;
            }

            if (_isTableRow(t)) {
                if (!inTable) {
                    let j = i + 1;
                    while (j < lines.length && !String(lines[j] || '').trim()) j++;
                    const next = j < lines.length ? String(lines[j] || '').trim() : '';
                    if (next && _isTableSepRow(next)) {
                        closeList();
                        inTable = true;
                        tableHeader = _parseTableCells(t);
                        tableRows = [];
                        i = j;
                        continue;
                    }
                } else {
                    if (_isTableSepRow(t)) {
                        continue;
                    }
                    tableRows.push(_parseTableCells(t));
                    continue;
                }
            }

            closeTable();
            closeList();
            html += '<p>' + inlineFormat(t) + '</p>';
        }
        closeTable();
        closeList();
        return html || '<p></p>';
    }

    function switchToChatMode() {
        if (welcome) welcome.style.display = 'none';
        if (inputBar) inputBar.style.display = '';
    }

    function switchToWelcomeMode() {
        if (welcome) welcome.style.display = '';
        if (inputBar) inputBar.style.display = 'none';
    }

    function addVolcMsg(role, content, isError, imageUrls) {
        switchToChatMode();
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble ' + role + (isError ? ' error' : '');
        const title = role === 'user' ? '我' : '智能竞赛客服机器人';
        const bodyHtml = role === 'assistant' ? renderMarkdown(content) : ('<p>' + nl2br(content) + '</p>');
        var urls = (role === 'user' && Array.isArray(imageUrls))
            ? imageUrls.map(function (u) { return String(u || '').trim(); }).filter(Boolean).slice(0, 8)
            : [];
        var thumbsHtml = '';
        if (urls.length) {
            thumbsHtml = '<div class="volc-user-msg-images" role="group" aria-label="提问附图">';
            urls.forEach(function (url, idx) {
                thumbsHtml += '<button type="button" class="volc-user-msg-thumb-btn" data-volc-user-img-idx="' + idx + '" title="查看大图">';
                thumbsHtml += '<img class="volc-user-msg-thumb" src="' + escapeHtml(url) + '" alt="" loading="lazy" draggable="false">';
                thumbsHtml += '</button>';
            });
            thumbsHtml += '</div>';
        }
        bubble.innerHTML =
            '<div class="chat-title">' + escapeHtml(title) + '</div>' +
            '<div class="chat-content">' + bodyHtml + '</div>' + thumbsHtml;
        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    var thinkingEl = null;
    function showThinking(show) {
        if (show) {
            if (thinkingEl) return;
            switchToChatMode();
            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble assistant volc-kb-thinking-bubble';
            bubble.innerHTML =
                '<div class="chat-title">' + escapeHtml('智能竞赛客服机器人') + '</div>' +
                '<div class="chat-content volc-kb-thinking-wrap">' +
                    '<div class="volc-kb-thinking-card">' +
                    '<span class="volc-kb-thinking-icon" aria-hidden="true">◈</span>' +
                    '<div><div class="volc-kb-thinking-title">思考中</div>' +
                    '<div class="volc-kb-thinking-sub">检索知识库并生成回答…</div></div>' +
                    '<span class="loading volc-kb-thinking-dots">…</span>' +
                    '</div>' +
                '</div>';
            thinkingEl = bubble;
            chatArea.appendChild(bubble);
            chatArea.scrollTop = chatArea.scrollHeight;
        } else {
            if (thinkingEl && thinkingEl.parentNode) thinkingEl.parentNode.removeChild(thinkingEl);
            thinkingEl = null;
        }
    }

    /** 登录失效或主动退出：清 sessionStorage 对话快照，去掉误恢复的「请先登录」等气泡 */
    function purgeVolcChatAfterAuthLoss() {
        try {
            clearVolcSession();
        } catch (e) {}
        try {
            showThinking(false);
        } catch (e2) {}
        if (chatArea) {
            chatArea.querySelectorAll('.chat-bubble').forEach(function (el) {
                el.remove();
            });
        }
        try {
            switchToWelcomeMode();
        } catch (e3) {}
    }

    var volcChatAbortController = null;
    var volcStreamInFlight = false;
    var volcActiveStreamUi = null;
    var VOLC_SEND_BTN_LABEL = '➤';
    var VOLC_STOP_BTN_LABEL = '终止';

    function getVolcDraftText() {
        var a = input && String(input.value || '').trim();
        var b = welcomeInput && String(welcomeInput.value || '').trim();
        return a || b || '';
    }

    function syncVolcComposerButtons() {
        var draft = getVolcDraftText();
        var showStop = volcStreamInFlight && !draft;
        [sendBtn, welcomeSendBtn].forEach(function (btn) {
            if (!btn) return;
            btn.disabled = false;
            if (showStop) {
                btn.textContent = VOLC_STOP_BTN_LABEL;
                btn.classList.add('is-volc-stop');
                btn.setAttribute('aria-label', '终止当前回答');
                btn.title = '终止当前回答';
            } else {
                btn.textContent = VOLC_SEND_BTN_LABEL;
                btn.classList.remove('is-volc-stop');
                btn.setAttribute('aria-label', '发送');
                btn.title = '发送';
            }
        });
    }

    function volcAbortInFlight() {
        try {
            if (volcChatAbortController) {
                volcChatAbortController.abort();
            }
        } catch (e) {}
        volcChatAbortController = null;
        showThinking(false);
        if (volcActiveStreamUi && volcActiveStreamUi.bubble && volcActiveStreamUi.bubble.parentNode) {
            try {
                volcActiveStreamUi.bubble.classList.add('error');
                var ae = volcActiveStreamUi.answerEl;
                if (ae) {
                    ae.innerHTML = '<p class="volc-kb-stream-err">' + escapeHtml('（已终止）') + '</p>';
                } else {
                    var wrap = volcActiveStreamUi.bubble.querySelector('.volc-kb-stream-wrap');
                    if (wrap) {
                        wrap.innerHTML = '<p class="volc-kb-stream-err">' + escapeHtml('（已终止）') + '</p>';
                    }
                }
            } catch (e2) {}
        }
        volcActiveStreamUi = null;
        volcStreamInFlight = false;
        syncVolcComposerButtons();
    }

    function onVolcComposerPrimaryAction() {
        if (volcStreamInFlight && !getVolcDraftText()) {
            volcAbortInFlight();
            try {
                saveVolcSession();
            } catch (e) {}
            return;
        }
        volcSend();
    }

    function onVolcComposerKeydown(e) {
        if (e.key !== 'Enter' || e.shiftKey) return;
        e.preventDefault();
        onVolcComposerPrimaryAction();
    }

    function requireLoginGuard() {
        const hasToken = !!localStorage.getItem('token');
        if (!hasToken && !_hasCookieToken()) {
            addVolcMsg('assistant', '请先登录！', true);
            showLoginTipAndGo();
            return false;
        }
        return true;
    }

    function getVolcAuthHeaderOnly() {
        var h = {};
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.getAuthHeaders === 'function') {
            var x = window.CR.Auth.getAuthHeaders();
            if (x && x.Authorization) h['Authorization'] = x.Authorization;
        }
        return h;
    }

    var volcUploadedUrls = [];

    function renderVolcPreviews() {
        var html = '';
        volcUploadedUrls.forEach(function (url, idx) {
            html += '<span class="volc-kb-thumb-wrap">';
            html += '<img class="volc-kb-thumb" src="' + escapeHtml(url) + '" alt="">';
            html += '<button type="button" class="volc-kb-thumb-remove" data-idx="' + idx + '" title="移除">×</button>';
            html += '</span>';
        });
        if (vkPreviewWelcome) vkPreviewWelcome.innerHTML = html;
        if (vkPreviewBar) vkPreviewBar.innerHTML = html;
        document.querySelectorAll('.volc-kb-thumb-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var i = parseInt(btn.getAttribute('data-idx'), 10);
                if (!isNaN(i)) {
                    volcUploadedUrls.splice(i, 1);
                    renderVolcPreviews();
                }
            });
        });
        var has = volcUploadedUrls.length > 0;
        if (vkUploadBtnWelcome) vkUploadBtnWelcome.classList.toggle('is-active', has);
        if (vkUploadBtnBar) vkUploadBtnBar.classList.toggle('is-active', has);
    }

    function clearVolcUploads() {
        volcUploadedUrls = [];
        renderVolcPreviews();
    }

    async function uploadVolcImageFiles(fileList) {
        var files = Array.prototype.slice.call(fileList || [], 0);
        if (!files.length) return;
        var remain = 8 - volcUploadedUrls.length;
        if (remain <= 0) {
            try { alert('最多 8 张图片'); } catch (e) {}
            return;
        }
        files = files.slice(0, remain);
        var base = (window.API_BASE || '');
        for (var i = 0; i < files.length; i++) {
            var fd = new FormData();
            fd.append('file', files[i]);
            try {
                var res = await fetch(base + '/api/volc_kb/upload_image', {
                    method: 'POST',
                    headers: getVolcAuthHeaderOnly(),
                    body: fd,
                    credentials: 'same-origin',
                });
                var j = await res.json();
                if (j.code !== 0) {
                    addVolcMsg('assistant', (j && j.message) || '图片上传失败', true);
                    break;
                }
                if (j.data && j.data.url) volcUploadedUrls.push(j.data.url);
            } catch (e) {
                addVolcMsg('assistant', (e && e.message) || '上传异常', true);
                break;
            }
        }
        renderVolcPreviews();
        if (vkFileInputWelcome) vkFileInputWelcome.value = '';
        if (vkFileInputBar) vkFileInputBar.value = '';
    }

    function bindVolcUpload(btn, finput) {
        if (!btn || !finput) return;
        btn.addEventListener('click', function () { finput.click(); });
        finput.addEventListener('change', function () {
            uploadVolcImageFiles(finput.files);
        });
    }
    bindVolcUpload(vkUploadBtnWelcome, vkFileInputWelcome);
    bindVolcUpload(vkUploadBtnBar, vkFileInputBar);
    renderVolcPreviews();

    function getAuthHeaders() {
        var h = { 'Content-Type': 'application/json' };
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.getAuthHeaders === 'function') {
            var x = window.CR.Auth.getAuthHeaders();
            if (x && x.Authorization) h['Authorization'] = x.Authorization;
        }
        return h;
    }

    var volcHistory = [];

    const contestCascade = document.getElementById('contestCascade');
    const contestCascadeBtn = document.getElementById('contestCascadeBtn');
    const contestCascadeDropdown = document.getElementById('contestCascadeDropdown');
    const contestCascadeLabel = document.getElementById('contestCascadeLabel');
    const contestCascadeCats = document.getElementById('contestCascadeCats');
    const contestCascadeItems = document.getElementById('contestCascadeItems');
    const contestCascadeAllInCat = document.getElementById('contestCascadeAllInCat');
    const contestCascadeRightTitle = document.getElementById('contestCascadeRightTitle');
    const welcomeTags = document.getElementById('welcomeTags');
    var _hotContestsCache = null;

    function renderWelcomeHotTags(containerEl, hot) {
        if (!containerEl) return;
        var tagIcons = ['🏆', '📋', '🎯', '⭐', '🔖', '📌'];
        containerEl.innerHTML = '';
        (hot.contests || []).forEach(function (c, idx) {
            var tag = document.createElement('button');
            tag.type = 'button';
            tag.className = 'welcome-tag';
            tag.title = '选择「' + (c.name || c.id) + '」';
            var ic = document.createElement('span');
            ic.className = 'welcome-tag-icon';
            ic.setAttribute('aria-hidden', 'true');
            ic.textContent = tagIcons[idx % tagIcons.length];
            var tx = document.createElement('span');
            tx.className = 'welcome-tag-text';
            tx.textContent = c.name || c.id;
            tag.appendChild(ic);
            tag.appendChild(tx);
            tag.addEventListener('click', function () {
                setContestSingle(c.id, c.name || c.id);
                var ta = null;
                if (welcome && welcome.style.display !== 'none' && welcomeInput) {
                    ta = welcomeInput;
                } else if (input) {
                    ta = input;
                }
                if (ta) {
                    ta.focus();
                    ta.placeholder = '关于「' + (c.name || c.id) + '」的问题...';
                }
            });
            containerEl.appendChild(tag);
        });
    }

    function applyWelcomeHotTagsPolicy() {
        if (!welcomeTags) return;
        var sub = document.querySelector('#welcome .welcome-subtitle');
        if (_isLoggedInForUi()) {
            welcomeTags.innerHTML = '';
            if (sub) sub.style.display = 'none';
            return;
        }
        if (sub) sub.style.display = '';
        if (_hotContestsCache) {
            renderWelcomeHotTags(welcomeTags, _hotContestsCache);
        }
    }

    var contestList = [];
    var contestCategories = [];
    var contestSelection = { mode: 'all' };
    var _activeCategoryKey = null;

    function contestNameById(cid) {
        var found = (contestList || []).filter(function (c) { return c.id === cid; })[0];
        return (found && (found.name || found.id)) || cid;
    }

    function updateContestCascadeLabel() {
        if (!contestCascadeLabel) return;
        if (contestSelection.mode === 'all') {
            contestCascadeLabel.textContent = '全部文档';
        } else if (contestSelection.mode === 'single') {
            contestCascadeLabel.textContent = contestSelection.name || contestSelection.id || '—';
        } else if (contestSelection.mode === 'category') {
            contestCascadeLabel.textContent = contestSelection.label || '整类赛事';
        } else {
            contestCascadeLabel.textContent = '全部文档';
        }
    }

    function setContestAll() {
        contestSelection = { mode: 'all' };
        _activeCategoryKey = null;
        updateContestCascadeLabel();
        if (contestCascadeItems) contestCascadeItems.innerHTML = '';
        if (contestCascadeAllInCat) contestCascadeAllInCat.hidden = true;
        if (contestCascadeRightTitle) contestCascadeRightTitle.textContent = '选择赛事';
        refreshCascadeActiveStyles();
    }

    function setContestSingle(id, name) {
        _activeCategoryKey = null;
        for (var i = 0; i < contestCategories.length; i++) {
            var ids = contestCategories[i].contest_ids || [];
            if (ids.indexOf(id) >= 0) {
                _activeCategoryKey = contestCategories[i].key;
                break;
            }
        }
        contestSelection = { mode: 'single', id: id, name: name || contestNameById(id) };
        updateContestCascadeLabel();
        refreshCascadeActiveStyles();
        closeContestCascade();
    }

    function setContestCategoryAll(cat) {
        var ids = (cat && cat.contest_ids) ? cat.contest_ids.slice() : [];
        var lab = (cat && cat.label) || (cat && cat.key) || '本类';
        _activeCategoryKey = cat && cat.key;
        contestSelection = {
            mode: 'category',
            categoryKey: cat && cat.key,
            ids: ids,
            label: lab + ' · 全部（' + ids.length + '）',
        };
        updateContestCascadeLabel();
        refreshCascadeActiveStyles();
        closeContestCascade();
    }

    function refreshCascadeActiveStyles() {
        try {
            if (contestCascadeCats) {
                contestCascadeCats.querySelectorAll('button').forEach(function (b) {
                    var k = b.getAttribute('data-cat');
                    var on = false;
                    if (k === '') on = contestSelection.mode === 'all';
                    else if (contestSelection.mode === 'category') on = k === (contestSelection.categoryKey || '');
                    else on = k === _activeCategoryKey;
                    b.classList.toggle('is-active', on);
                });
            }
            var sid = contestSelection.mode === 'single' ? contestSelection.id : null;
            if (contestCascadeItems && sid) {
                contestCascadeItems.querySelectorAll('button[data-id]').forEach(function (b) {
                    b.classList.toggle('is-active', b.getAttribute('data-id') === sid);
                });
            }
        } catch (e) {}
    }

    function renderRightColumn(catKey) {
        if (!contestCascadeItems || !contestCascadeAllInCat || !contestCascadeRightTitle) return;
        var cat = (contestCategories || []).filter(function (c) { return c.key === catKey; })[0];
        contestCascadeItems.innerHTML = '';
        if (!cat) {
            contestCascadeAllInCat.hidden = true;
            contestCascadeRightTitle.textContent = '选择赛事';
            return;
        }
        _activeCategoryKey = catKey;
        contestCascadeRightTitle.textContent = cat.label || cat.key;
        contestCascadeAllInCat.hidden = false;
        var n = (cat.contest_ids || []).length;
        contestCascadeAllInCat.textContent = '全部「' + (cat.label || cat.key) + '」赛事（' + n + ' 项）';
        contestCascadeAllInCat.onclick = function () { setContestCategoryAll(cat); };

        (cat.contest_ids || []).forEach(function (cid) {
            var li = document.createElement('li');
            var bt = document.createElement('button');
            bt.type = 'button';
            bt.setAttribute('data-id', cid);
            bt.textContent = contestNameById(cid);
            bt.addEventListener('click', function () {
                setContestSingle(cid, contestNameById(cid));
            });
            li.appendChild(bt);
            contestCascadeItems.appendChild(li);
        });
        refreshCascadeActiveStyles();
    }

    function openContestCascade() {
        if (!contestCascadeDropdown || !contestCascadeBtn) return;
        contestCascadeDropdown.hidden = false;
        contestCascadeBtn.classList.add('is-open');
        contestCascadeBtn.setAttribute('aria-expanded', 'true');
    }

    function closeContestCascade() {
        if (!contestCascadeDropdown || !contestCascadeBtn) return;
        contestCascadeDropdown.hidden = true;
        contestCascadeBtn.classList.remove('is-open');
        contestCascadeBtn.setAttribute('aria-expanded', 'false');
    }

    function toggleContestCascade() {
        if (!contestCascadeDropdown || contestCascadeDropdown.hidden) openContestCascade();
        else closeContestCascade();
    }

    function initContestCascadeUi(data) {
        contestList = data.contests || [];
        contestCategories = data.categories || [];
        if (!contestCascadeCats) return;
        contestCascadeCats.innerHTML = '';

        var bAll = document.createElement('button');
        bAll.type = 'button';
        bAll.textContent = '全部文档';
        bAll.setAttribute('data-cat', '');
        bAll.addEventListener('click', function () {
            setContestAll();
            if (contestCascadeItems) contestCascadeItems.innerHTML = '';
            if (contestCascadeAllInCat) contestCascadeAllInCat.hidden = true;
            if (contestCascadeRightTitle) contestCascadeRightTitle.textContent = '选择赛事';
            refreshCascadeActiveStyles();
            closeContestCascade();
        });
        var li0 = document.createElement('li');
        li0.appendChild(bAll);
        contestCascadeCats.appendChild(li0);

        contestCategories.forEach(function (cat) {
            var li = document.createElement('li');
            var bt = document.createElement('button');
            bt.type = 'button';
            bt.textContent = cat.label || cat.key;
            bt.setAttribute('data-cat', cat.key);
            bt.addEventListener('click', function () {
                renderRightColumn(cat.key);
            });
            li.appendChild(bt);
            contestCascadeCats.appendChild(li);
        });
        updateContestCascadeLabel();
        refreshCascadeActiveStyles();
    }

    if (contestCascadeBtn) {
        contestCascadeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            toggleContestCascade();
        });
    }
    document.addEventListener('click', function (e) {
        if (!contestCascade || !contestCascadeDropdown) return;
        if (contestCascade.contains(e.target)) return;
        closeContestCascade();
    });

    function getVolcContestId() {
        try {
            if (contestSelection && contestSelection.mode === 'single' && contestSelection.id) {
                return String(contestSelection.id);
            }
        } catch (e) {}
        return '';
    }

    /** 末尾「参考文档」：仅列举 PDF 文件名（去重） */
    function buildVolcRefsBottomHtml(refs) {
        if (!refs || !refs.length) return '';
        var seen = {};
        var names = [];
        refs.forEach(function (r) {
            var n = (r && r.source_pdf) ? String(r.source_pdf).trim() : '';
            if (n && !seen[n]) {
                seen[n] = true;
                names.push(n);
            }
        });
        if (!names.length) return '';
        var h = '<div class="volc-kb-refs-bottom"><div class="volc-kb-refs-bottom-title">📖 参考文档（' + names.length + '）</div><ul class="volc-kb-refs-bottom-list">';
        names.forEach(function (name) {
            h += '<li><span class="volc-kb-ref-pdf-icon" aria-hidden="true">📄</span><span class="volc-kb-ref-pdf-name">' + escapeHtml(name) + '</span></li>';
        });
        h += '</ul></div>';
        return h;
    }

    /** 资料关联图：缩略图条，点击进全屏预览（与主站 imgViewer 一致） */
    function buildVolcRefImagesHtml(refs) {
        if (!refs || !refs.length) return { html: '', urls: [] };
        var urls = [];
        var seen = {};
        refs.forEach(function (r) {
            var u = r && r.related_image ? String(r.related_image).trim() : '';
            if (u && !seen[u]) {
                seen[u] = true;
                urls.push(u);
            }
        });
        if (!urls.length) return { html: '', urls: [] };
        var h = '<div class="volc-kb-answer-refimgs"><div class="volc-kb-answer-refimgs-title">资料插图</div><div class="volc-kb-answer-refimgs-row">';
        urls.forEach(function (url, idx) {
            h += '<button type="button" class="volc-kb-answer-thumb-btn" data-volc-img-idx="' + idx + '" title="查看大图">';
            h += '<img class="volc-kb-answer-thumb" src="' + escapeHtml(url) + '" alt="资料插图" loading="lazy" draggable="false">';
            h += '</button>';
        });
        h += '</div></div>';
        return { html: h, urls: urls };
    }

    function bindVolcAnswerRefImages(refsBottomHost, urls) {
        if (!refsBottomHost || !urls || !urls.length) return;
        var row = refsBottomHost.querySelector('.volc-kb-answer-refimgs');
        if (!row) return;
        row.querySelectorAll('.volc-kb-answer-thumb-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var i = parseInt(btn.getAttribute('data-volc-img-idx'), 10) || 0;
                openVolcImageViewer(urls, i);
            });
        });
    }

    /** sessionStorage 恢复后，从 DOM 重建资料插图点击（innerHTML 会丢掉监听器）；用户附图由 chatArea 委托点击 */
    function rebindVolcRestoredChat() {
        if (!chatArea) return;
        chatArea.querySelectorAll('.volc-kb-refs-bottom-host').forEach(function (host) {
            var thumbs = host.querySelectorAll('.volc-kb-answer-thumb');
            var urls = [];
            thumbs.forEach(function (img) {
                urls.push(img.src);
            });
            if (urls.length) bindVolcAnswerRefImages(host, urls);
        });
    }

    var VOLC_SESSION_KEY = 'volc_kb_session_v1';
    var VOLC_REQUERY_KEY = 'volc_kb_requery_v1';

    function volcHasRequeryPayload() {
        try {
            return !!sessionStorage.getItem(VOLC_REQUERY_KEY);
        } catch (e) {
            return false;
        }
    }

    function saveVolcSession() {
        try {
            if (!chatArea || !chatArea.querySelector('.chat-bubble')) {
                sessionStorage.removeItem(VOLC_SESSION_KEY);
                return;
            }
            sessionStorage.setItem(VOLC_SESSION_KEY, JSON.stringify({
                chatHtml: chatArea.innerHTML,
                volcHistory: volcHistory,
                contestSelection: contestSelection,
                activeCategoryKey: _activeCategoryKey,
                deepThinkEnabled: deepThinkEnabled,
            }));
        } catch (e) {}
    }

    function clearVolcSession() {
        try {
            sessionStorage.removeItem(VOLC_SESSION_KEY);
        } catch (e) {}
    }

    function restoreVolcSession() {
        try {
            var raw = sessionStorage.getItem(VOLC_SESSION_KEY);
            if (!raw) return false;
            var o = JSON.parse(raw);
            if (!o || !o.chatHtml || !String(o.chatHtml).trim()) return false;
            chatArea.innerHTML = o.chatHtml;
            if (Array.isArray(o.volcHistory)) volcHistory = o.volcHistory;
            if (o.contestSelection && typeof o.contestSelection === 'object') {
                contestSelection = o.contestSelection;
            }
            if (o.activeCategoryKey !== undefined && o.activeCategoryKey !== null) {
                _activeCategoryKey = o.activeCategoryKey;
            }
            if (typeof o.deepThinkEnabled === 'boolean') {
                deepThinkEnabled = o.deepThinkEnabled;
                _syncDeepThinkUi();
            }
            switchToChatMode();
            rebindVolcRestoredChat();
            try {
                chatArea.scrollTop = chatArea.scrollHeight;
            } catch (e2) {}
            return true;
        } catch (e) {
            return false;
        }
    }

    window.addEventListener('beforeunload', function () {
        saveVolcSession();
    });
    document.addEventListener('click', function (e) {
        var a = e.target && e.target.closest && e.target.closest('a[href="/history"]');
        if (a) saveVolcSession();
    }, true);

    var _volcRestoredFromSession = false;

    var _volcViewerUrls = [];
    var _volcViewerIdx = 0;
    function openVolcImageViewer(urls, idx) {
        _volcViewerUrls = Array.isArray(urls) ? urls.slice() : [];
        if (!_volcViewerUrls.length) return;
        _volcViewerIdx = Math.max(0, Math.min(idx || 0, _volcViewerUrls.length - 1));
        var viewerEl = document.getElementById('imgViewer');
        var viewerImgEl = document.getElementById('imgViewerImg');
        var viewerMetaEl = document.getElementById('imgViewerMeta');
        var viewerDl = document.getElementById('imgViewerDownload');
        if (!viewerEl || !viewerImgEl) return;
        viewerImgEl.src = _volcViewerUrls[_volcViewerIdx];
        if (viewerMetaEl) viewerMetaEl.textContent = '图片 ' + (_volcViewerIdx + 1) + '/' + _volcViewerUrls.length;
        if (viewerDl) {
            viewerDl.href = _volcViewerUrls[_volcViewerIdx];
            viewerDl.setAttribute('download', 'ref_' + (_volcViewerIdx + 1) + '.jpg');
        }
        viewerEl.classList.add('is-open');
        viewerEl.setAttribute('aria-hidden', 'false');
    }
    (function setupVolcImgViewerChrome() {
        var viewerEl = document.getElementById('imgViewer');
        var viewerImgEl = document.getElementById('imgViewerImg');
        if (!viewerEl || !viewerImgEl) return;
        function volcViewerSyncMeta() {
            var viewerMetaEl = document.getElementById('imgViewerMeta');
            if (viewerMetaEl && _volcViewerUrls.length) {
                viewerMetaEl.textContent = '图片 ' + (_volcViewerIdx + 1) + '/' + _volcViewerUrls.length;
            }
            var viewerDl = document.getElementById('imgViewerDownload');
            if (viewerDl && _volcViewerUrls[_volcViewerIdx]) {
                viewerDl.href = _volcViewerUrls[_volcViewerIdx];
            }
        }
        function closeV() {
            viewerEl.classList.remove('is-open');
            viewerEl.setAttribute('aria-hidden', 'true');
            try { viewerImgEl.removeAttribute('src'); } catch (e) {}
            _volcViewerUrls = [];
        }
        document.getElementById('imgViewerClose')?.addEventListener('click', function (e) {
            e.stopPropagation();
            closeV();
        });
        viewerEl.addEventListener('click', function (e) {
            if (e.target === viewerEl) closeV();
        });
        document.getElementById('imgViewerPrev')?.addEventListener('click', function (e) {
            e.stopPropagation();
            if (!_volcViewerUrls.length) return;
            _volcViewerIdx = (_volcViewerIdx - 1 + _volcViewerUrls.length) % _volcViewerUrls.length;
            viewerImgEl.src = _volcViewerUrls[_volcViewerIdx];
            volcViewerSyncMeta();
        });
        document.getElementById('imgViewerNext')?.addEventListener('click', function (e) {
            e.stopPropagation();
            if (!_volcViewerUrls.length) return;
            _volcViewerIdx = (_volcViewerIdx + 1) % _volcViewerUrls.length;
            viewerImgEl.src = _volcViewerUrls[_volcViewerIdx];
            volcViewerSyncMeta();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            if (!viewerEl.classList.contains('is-open')) return;
            closeV();
        });
    })();

    if (chatArea) {
        chatArea.addEventListener('click', function (e) {
            var th = e.target.closest('.volc-thinking-header');
            if (th && chatArea.contains(th)) {
                var section = th.closest('[data-volc-thinking-root]');
                if (section && !section.classList.contains('is-hidden')) {
                    e.preventDefault();
                    e.stopPropagation();
                    section.classList.toggle('is-collapsed');
                    var collapsed = section.classList.contains('is-collapsed');
                    th.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                    if (volcActiveStreamUi && volcActiveStreamUi.bubble && volcActiveStreamUi.bubble.contains(section)) {
                        if (section.classList.contains('is-streaming')) {
                            volcActiveStreamUi.thinkingUserCollapsed = collapsed;
                        }
                    }
                }
                return;
            }
            var btn = e.target.closest('.volc-user-msg-thumb-btn');
            if (!btn || !chatArea.contains(btn)) return;
            e.preventDefault();
            e.stopPropagation();
            var wrap = btn.closest('.volc-user-msg-images');
            if (!wrap) return;
            var urls = [];
            wrap.querySelectorAll('.volc-user-msg-thumb').forEach(function (im) {
                urls.push(im.getAttribute('src') || im.src || '');
            });
            var idx = parseInt(btn.getAttribute('data-volc-user-img-idx'), 10) || 0;
            openVolcImageViewer(urls, idx);
        });
    }

    /** 正文流中是否已出现「正式回答」标题（HTML 或 Markdown），用于与分通道 SSE 互补判断 */
    function volcFormalAnswerHeaderSeen(buf) {
        var s = stripVolcRawTags(buf == null ? '' : String(buf));
        if (/<h3[^>]*>\s*正式回答\s*<\/h3>/i.test(s)) return true;
        if (/(^|\n)#{1,6}\s*正式回答\b/.test(s)) return true;
        return false;
    }

    /**
     * 火山侧常见：全文在一个 content 通道里，用 Markdown 标题「推理过程」「正式回答」分段（与独立 reasoning SSE 二选一或混用）。
     * 若检测到「正式回答」标题，返回标题后的正文，及「推理过程」标题后的推理 Markdown（可空）。
     */
    function trySplitVolcEmbeddedReasoningFormal(text) {
        var t = String(text == null ? '' : text).replace(/\r\n/g, '\n');
        var formalRe = /\n(#{1,6})\s*正式回答\s*[：:]?\s*\n/;
        var m = formalRe.exec(t);
        if (!m) {
            formalRe = /^(#{1,6})\s*正式回答\s*[：:]?\s*\n/m;
            m = formalRe.exec(t);
        }
        if (!m) return null;
        var cut = m.index + m[0].length;
        var before = t.slice(0, m.index);
        var formalMd = t.slice(cut);
        var reasonRe = /^(#{1,6})\s*推理过程\s*[：:]?\s*\n/m;
        var reasonMd = before.replace(reasonRe, '').trim();
        return { reasonMarkdown: reasonMd, formalMarkdown: formalMd };
    }

    /**
     * @param {boolean} deepThinkOn 是否启用深度思考（未启用则整块隐藏）
     */
    function createVolcStreamAssistantBubble(deepThinkOn) {
        switchToChatMode();
        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble assistant volc-kb-stream-bubble';
        var thinkClass = 'volc-thinking-section';
        if (deepThinkOn) {
            thinkClass += ' is-streaming is-hidden is-collapsed';
        } else {
            thinkClass += ' is-hidden';
        }
        bubble.innerHTML =
            '<div class="chat-title">' + escapeHtml('智能竞赛客服机器人') + '</div>' +
            '<div class="chat-content volc-kb-stream-wrap">' +
            '<div class="' + thinkClass + '" data-volc-thinking-root>' +
            '<button type="button" class="volc-thinking-header" aria-expanded="false" aria-label="推理过程，点击展开或折叠">' +
            '<span class="volc-thinking-icon volc-thinking-icon--loading" aria-hidden="true"></span>' +
            '<span class="volc-thinking-header-main">' +
            '<span class="volc-thinking-title">推理过程</span>' +
            '<span class="volc-thinking-fold-btn" title="折叠 / 展开推理过程"><span class="volc-thinking-chevron" aria-hidden="true">▲</span></span>' +
            '</span>' +
            '</button>' +
            '<div class="volc-thinking-body">' +
            '<pre class="volc-thinking-pre volc-thinking-content"></pre>' +
            '<div class="volc-thinking-md volc-thinking-content" hidden></div>' +
            '</div>' +
            '</div>' +
            '<div class="volc-kb-answer-md volc-answer-content"></div>' +
            '<div class="volc-kb-refs-bottom-host"></div>' +
            '</div>';
        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;
        var thinkingSection = bubble.querySelector('[data-volc-thinking-root]');
        var thinkingHeader = bubble.querySelector('.volc-thinking-header');
        var thinkingTitle = bubble.querySelector('.volc-thinking-title');
        var thinkingIcon = bubble.querySelector('.volc-thinking-icon');
        var thinkingBody = bubble.querySelector('.volc-thinking-body');
        var thinkingPre = bubble.querySelector('.volc-thinking-pre');
        var thinkingMd = bubble.querySelector('.volc-thinking-md');
        var refsBottomHost = bubble.querySelector('.volc-kb-refs-bottom-host');
        return {
            bubble: bubble,
            thinkingSection: thinkingSection,
            thinkingHeader: thinkingHeader,
            thinkingTitle: thinkingTitle,
            thinkingIcon: thinkingIcon,
            thinkingBody: thinkingBody,
            thinkingPre: thinkingPre,
            thinkingMd: thinkingMd,
            answerEl: bubble.querySelector('.volc-kb-answer-md'),
            refsBottomHost: refsBottomHost,
            thinkingUserCollapsed: false,
            formalAnswerStreamBegun: false,
            embeddedSplitActive: false,
        };
    }

    function volcFinishThinkingUi(ui, fullReason, thinkStartedAt) {
        if (!ui || !ui.thinkingSection) return;
        ui.thinkingUserCollapsed = false;
        if (!fullReason || !String(fullReason).trim()) {
            ui.thinkingSection.classList.remove('is-streaming');
            ui.thinkingSection.classList.add('is-hidden');
            if (ui.thinkingMd) {
                ui.thinkingMd.innerHTML = '';
                ui.thinkingMd.setAttribute('hidden', '');
                ui.thinkingMd.style.display = 'none';
            }
            if (ui.thinkingPre) ui.thinkingPre.style.display = '';
            return;
        }
        ui.thinkingSection.classList.remove('is-streaming');
        ui.thinkingSection.classList.add('is-collapsed');
        ui.thinkingSection.classList.remove('is-hidden');
        if (ui.thinkingTitle) {
            if (thinkStartedAt) {
                var sec = Math.max(0, (Date.now() - thinkStartedAt) / 1000);
                ui.thinkingTitle.textContent = '已完成内部推理（' + sec.toFixed(2) + ' 秒）';
            } else {
                ui.thinkingTitle.textContent = '已完成内部推理';
            }
        }
        if (ui.thinkingIcon) {
            ui.thinkingIcon.classList.remove('volc-thinking-icon--loading');
            ui.thinkingIcon.classList.add('volc-thinking-icon--done');
            ui.thinkingIcon.textContent = '';
        }
        if (ui.thinkingHeader) {
            ui.thinkingHeader.setAttribute('aria-expanded', 'false');
            ui.thinkingHeader.setAttribute(
                'aria-label',
                (ui.thinkingTitle && ui.thinkingTitle.textContent) || '推理过程，点击展开或折叠'
            );
        }
    }

    async function readVolcSseStream(response, onEvent) {
        var reader = response.body && response.body.getReader();
        if (!reader) return;
        var dec = new TextDecoder();
        var buf = '';
        while (true) {
            var step = await reader.read();
            if (step.done) break;
            buf += dec.decode(step.value, { stream: true });
            buf = buf.replace(/\r\n/g, '\n');
            var delim = '\n\n';
            var idx;
            while ((idx = buf.indexOf(delim)) >= 0) {
                var block = buf.slice(0, idx).trim();
                buf = buf.slice(idx + delim.length);
                if (block.indexOf('data:') !== 0) continue;
                var json = block.slice(5).trim();
                if (!json) continue;
                try {
                    onEvent(JSON.parse(json));
                } catch (e) {
                    try { window.console && window.console.warn('volc sse parse', e); } catch (e2) {}
                }
            }
        }
    }

    async function volcSend() {
        if (!requireLoginGuard()) return;
        var msg = (input ? input.value.trim() : '');
        if (!msg && welcomeInput) msg = welcomeInput.value.trim();
        if (!msg) return;

        // 新一轮开始：先禁用分享，待 done 回包携带 question_id 后再启用
        volcLastQuestionId = null;
        setShareEnabled(false, '请等待本轮回答完成后再分享');

        if (volcStreamInFlight) {
            volcAbortInFlight();
        }

        volcStreamInFlight = true;
        volcChatAbortController = new AbortController();
        var acSignal = volcChatAbortController.signal;
        syncVolcComposerButtons();

        if (input) input.value = '';
        if (welcomeInput) welcomeInput.value = '';
        syncVolcComposerButtons();

        var sentImageUrls = volcUploadedUrls.slice();
        addVolcMsg('user', msg, false, sentImageUrls);
        showThinking(true);

        // 火山 knowledge/service/chat：图片用顶级 image_query（单图 URL），不是 OpenAI 式 messages 多模态
        var body = {
            message: msg,
            history: volcHistory,
            image_urls: sentImageUrls,
            image_query: sentImageUrls[0] || '',
            stream: true,
            deep_think: !!deepThinkEnabled,
            competition_id: getVolcContestId(),
        };

        var base = (window.API_BASE || '');
        var headers = getAuthHeaders();
        headers['Accept'] = 'text/event-stream';

        try {
            var res = await fetch(base + '/api/volc_kb/chat', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(body),
                credentials: 'same-origin',
                signal: acSignal,
            });

            showThinking(false);

            var ct = (res.headers.get('content-type') || '').toLowerCase();
            if (!res.ok) {
                var errText = await res.text();
                var errMsg = '请求失败';
                try {
                    var ej = JSON.parse(errText);
                    errMsg = (ej && ej.message) || errText || errMsg;
                } catch (e) {
                    errMsg = errText || errMsg;
                }
                addVolcMsg('assistant', errMsg, true);
                return;
            }

            if (ct.indexOf('text/event-stream') === -1) {
                var j = await res.json();
                if (j.code !== 0) {
                    addVolcMsg('assistant', j.message || '请求失败', true);
                    return;
                }
                var ans0 = stripVolcRawTags((j.data && j.data.answer) || '');
                var ref0 = (j.data && j.data.references) || [];
                var shell = createVolcStreamAssistantBubble(!!deepThinkEnabled);
                var rsn = (j.data && j.data.reasoning) ? String(j.data.reasoning) : '';
                var feJson = trySplitVolcEmbeddedReasoningFormal(ans0);
                if (rsn.trim()) {
                    if (shell.thinkingMd) {
                        shell.thinkingMd.innerHTML = '';
                        shell.thinkingMd.setAttribute('hidden', '');
                        shell.thinkingMd.style.display = 'none';
                    }
                    if (shell.thinkingPre) {
                        shell.thinkingPre.style.display = '';
                        shell.thinkingPre.textContent = rsn;
                    }
                    shell.answerEl.innerHTML = renderMarkdown(ans0);
                    volcFinishThinkingUi(shell, rsn, null);
                } else if (feJson && feJson.reasonMarkdown.trim()) {
                    if (shell.thinkingPre) shell.thinkingPre.style.display = 'none';
                    if (shell.thinkingMd) {
                        shell.thinkingMd.removeAttribute('hidden');
                        shell.thinkingMd.style.display = 'block';
                        shell.thinkingMd.innerHTML = renderMarkdown(feJson.reasonMarkdown);
                    }
                    shell.answerEl.innerHTML = renderMarkdown(feJson.formalMarkdown);
                    volcFinishThinkingUi(shell, feJson.reasonMarkdown, null);
                } else {
                    shell.thinkingSection.classList.add('is-hidden');
                    shell.answerEl.innerHTML = renderMarkdown(ans0);
                }
                var imgPack0 = buildVolcRefImagesHtml(ref0);
                if (shell.refsBottomHost) {
                    shell.refsBottomHost.innerHTML = (imgPack0.html || '') + buildVolcRefsBottomHtml(ref0);
                    bindVolcAnswerRefImages(shell.refsBottomHost, imgPack0.urls || []);
                }
                var uTurn = { role: 'user', content: msg };
                if (sentImageUrls.length) uTurn.image_urls = sentImageUrls.slice();
                volcHistory.push(uTurn);
                volcHistory.push({ role: 'assistant', content: ans0 });
                if (volcHistory.length > 40) volcHistory = volcHistory.slice(-40);
                clearVolcUploads();
                return;
            }

            var ui = createVolcStreamAssistantBubble(!!deepThinkEnabled);
            volcActiveStreamUi = ui;
            var fullReason = '';
            var fullAns = '';
            var thinkStartedAt = null;
            var contentStarted = false;
            var pendingRefs = [];

            try {
                await readVolcSseStream(res, function (ev) {
                    if (!ev || !ev.type) return;
                    if (ev.type === 'references') {
                        pendingRefs = ev.references || [];
                    } else if (ev.type === 'reasoning' && ev.delta) {
                        if (contentStarted) return;
                        fullReason += ev.delta;
                        if (!thinkStartedAt) thinkStartedAt = Date.now();
                        if (ui.thinkingSection) {
                            ui.thinkingSection.classList.remove('is-hidden');
                            ui.thinkingSection.classList.add('is-streaming');
                            if (!ui.thinkingUserCollapsed) {
                                ui.thinkingSection.classList.remove('is-collapsed');
                                if (ui.thinkingHeader) {
                                    ui.thinkingHeader.setAttribute('aria-expanded', 'true');
                                }
                            }
                        }
                        if (ui.thinkingTitle) ui.thinkingTitle.textContent = '推理过程 · 思考中';
                        if (ui.thinkingIcon) {
                            ui.thinkingIcon.classList.remove('volc-thinking-icon--done');
                            ui.thinkingIcon.classList.add('volc-thinking-icon--loading');
                            ui.thinkingIcon.textContent = '';
                        }
                        if (ui.thinkingMd) {
                            ui.thinkingMd.innerHTML = '';
                            ui.thinkingMd.setAttribute('hidden', '');
                            ui.thinkingMd.style.display = 'none';
                        }
                        if (ui.thinkingPre) {
                            ui.thinkingPre.style.display = '';
                            ui.thinkingPre.textContent = fullReason;
                            ui.thinkingPre.scrollTop = ui.thinkingPre.scrollHeight;
                        }
                        chatArea.scrollTop = chatArea.scrollHeight;
                    } else if (ev.type === 'content' && ev.delta) {
                        fullAns += ev.delta;
                        if (!thinkStartedAt) thinkStartedAt = Date.now();
                        var raw = stripVolcRawTags(fullAns);
                        var emb = trySplitVolcEmbeddedReasoningFormal(raw);
                        if (emb) {
                            contentStarted = true;
                            ui.formalAnswerStreamBegun = true;
                            if (emb.reasonMarkdown.trim()) {
                                ui.thinkingUserCollapsed = false;
                                if (!ui.embeddedSplitActive) {
                                    ui.embeddedSplitActive = true;
                                    if (ui.thinkingPre) ui.thinkingPre.style.display = 'none';
                                    if (ui.thinkingMd) {
                                        ui.thinkingMd.removeAttribute('hidden');
                                        ui.thinkingMd.style.display = 'block';
                                    }
                                    volcFinishThinkingUi(ui, emb.reasonMarkdown, thinkStartedAt);
                                }
                                if (ui.thinkingMd) {
                                    ui.thinkingMd.innerHTML = renderMarkdown(emb.reasonMarkdown);
                                }
                            } else {
                                if (!ui.embeddedSplitActive) {
                                    ui.embeddedSplitActive = true;
                                    ui.thinkingSection.classList.remove('is-streaming');
                                    ui.thinkingSection.classList.add('is-hidden');
                                }
                            }
                            ui.answerEl.innerHTML =
                                '<pre class="volc-kb-answer-stream">' +
                                escapeHtml(emb.formalMarkdown) +
                                '</pre>';
                        } else {
                            if (!ui.formalAnswerStreamBegun) {
                                if (fullReason.trim()) {
                                    if (volcFormalAnswerHeaderSeen(fullAns) || raw.trim().length > 0) {
                                        ui.formalAnswerStreamBegun = true;
                                        contentStarted = true;
                                        ui.thinkingUserCollapsed = false;
                                        volcFinishThinkingUi(ui, fullReason, thinkStartedAt);
                                    }
                                } else if (volcFormalAnswerHeaderSeen(fullAns) || raw.trim().length > 0) {
                                    ui.formalAnswerStreamBegun = true;
                                    contentStarted = true;
                                    ui.thinkingUserCollapsed = false;
                                }
                            }
                            ui.answerEl.innerHTML =
                                '<pre class="volc-kb-answer-stream">' + escapeHtml(raw) + '</pre>';
                        }
                        chatArea.scrollTop = chatArea.scrollHeight;
                    } else if (ev.type === 'done') {
                        if (!ui.formalAnswerStreamBegun && stripVolcRawTags(fullAns).trim().length > 0) {
                            ui.formalAnswerStreamBegun = true;
                            contentStarted = true;
                            ui.thinkingUserCollapsed = false;
                            if (fullReason.trim()) {
                                volcFinishThinkingUi(ui, fullReason, thinkStartedAt);
                            }
                        }
                        if (!contentStarted && fullReason.trim()) {
                            volcFinishThinkingUi(ui, fullReason, thinkStartedAt);
                        }
                        if (ev.history && Array.isArray(ev.history) && ev.history.length) {
                            volcHistory = ev.history.slice();
                        } else {
                            var uTurn2 = { role: 'user', content: msg };
                            if (sentImageUrls.length) uTurn2.image_urls = sentImageUrls.slice();
                            volcHistory.push(uTurn2);
                            volcHistory.push({ role: 'assistant', content: fullAns });
                            if (volcHistory.length > 40) volcHistory = volcHistory.slice(-40);
                        }
                        var cleanAns = stripVolcRawTags(fullAns);
                        var fe = trySplitVolcEmbeddedReasoningFormal(cleanAns);
                        if (fe && fe.reasonMarkdown.trim()) {
                            if (ui.thinkingPre) ui.thinkingPre.style.display = 'none';
                            if (ui.thinkingMd) {
                                ui.thinkingMd.removeAttribute('hidden');
                                ui.thinkingMd.style.display = 'block';
                                ui.thinkingMd.innerHTML = renderMarkdown(fe.reasonMarkdown);
                            }
                            ui.answerEl.innerHTML = renderMarkdown(fe.formalMarkdown);
                            volcFinishThinkingUi(ui, fe.reasonMarkdown, thinkStartedAt);
                        } else if (fe) {
                            ui.answerEl.innerHTML = renderMarkdown(fe.formalMarkdown);
                            volcFinishThinkingUi(ui, fullReason, thinkStartedAt);
                        } else {
                            ui.answerEl.innerHTML = renderMarkdown(cleanAns);
                            volcFinishThinkingUi(ui, fullReason, thinkStartedAt);
                        }
                        var imgPack = buildVolcRefImagesHtml(pendingRefs);
                        if (ui.refsBottomHost) {
                            ui.refsBottomHost.innerHTML = (imgPack.html || '') + buildVolcRefsBottomHtml(pendingRefs);
                            bindVolcAnswerRefImages(ui.refsBottomHost, imgPack.urls || []);
                        }
                        clearVolcUploads();
                        // 分享：后端会在 done 事件里返回 question_id（写入历史成功时）
                        if (ev && ev.question_id) {
                            volcLastQuestionId = ev.question_id;
                            setShareEnabled(true, '分享当前这条问答');
                        } else {
                            // 兜底：部分路径下 done 未携带 question_id，则从历史中取最新一条
                            volcLastQuestionId = null;
                            if (window.axios) {
                                window.axios.get('/api/history', { params: { limit: 1, offset: 0 } }).then(function (res2) {
                                    var j2 = res2 && res2.data ? res2.data : null;
                                    var items = j2 && j2.code === 0 && j2.data && Array.isArray(j2.data.items) ? j2.data.items : [];
                                    var latest = items && items[0] ? items[0] : null;
                                    if (latest && latest.id) {
                                        volcLastQuestionId = latest.id;
                                        setShareEnabled(true, '分享当前这条问答');
                                    } else {
                                        setShareEnabled(false, '本条问答未写入历史，无法分享');
                                    }
                                }).catch(function () {
                                    setShareEnabled(false, '本条问答未写入历史，无法分享');
                                });
                            } else {
                                setShareEnabled(false, '本条问答未写入历史，无法分享');
                            }
                        }
                    } else if (ev.type === 'error') {
                        ui.bubble.classList.add('error');
                        var errLine = ev.message || '错误';
                        if (ev.detail) {
                            errLine += '\n' + String(ev.detail).slice(0, 800);
                        }
                        ui.answerEl.innerHTML = '<p class="volc-kb-stream-err">' + escapeHtml(errLine).replace(/\n/g, '<br>') + '</p>';
                    }
                });
            } catch (readErr) {
                if (!readErr || readErr.name !== 'AbortError') {
                    throw readErr;
                }
            }
        } catch (e) {
            showThinking(false);
            if (e && e.name === 'AbortError') {
                /* 用户终止或新提问覆盖，已在 volcAbortInFlight 处理 UI */
            } else {
                var m = (e && e.message) || '网络错误';
                addVolcMsg('assistant', String(m), true);
            }
        } finally {
            volcStreamInFlight = false;
            volcChatAbortController = null;
            volcActiveStreamUi = null;
            syncVolcComposerButtons();
            try {
                saveVolcSession();
            } catch (e3) {}
        }
    }

    (function loadContests() {
        function tryApplyVolcRequeryPayload() {
            if (_volcRestoredFromSession) return false;
            try {
                var raw = sessionStorage.getItem(VOLC_REQUERY_KEY);
                if (!raw) return false;
                sessionStorage.removeItem(VOLC_REQUERY_KEY);
                var rq = JSON.parse(raw);
                if (!rq || typeof rq !== 'object') return false;
                var qtext = String(rq.query || '').trim();
                var imgs = Array.isArray(rq.image_urls) ? rq.image_urls.filter(Boolean).slice(0, 8) : [];
                if (!qtext && !imgs.length) return false;
                var cid = String(rq.contest || '').trim();
                if (cid) setContestSingle(cid, contestNameById(cid));
                volcUploadedUrls = imgs;
                renderVolcPreviews();
                if (welcome && welcome.style.display !== 'none' && welcomeInput) {
                    welcomeInput.value = qtext;
                } else if (input) {
                    input.value = qtext;
                }
                switchToChatMode();
                syncVolcComposerButtons();
                setTimeout(function () {
                    if (qtext) volcSend();
                }, 450);
                try {
                    window.history.replaceState({}, '', '/volc-kb');
                } catch (e2) {}
                return true;
            } catch (e) {
                return false;
            }
        }

        function onContestsLoaded(data) {
            initContestCascadeUi(data);
            if (_volcRestoredFromSession) {
                updateContestCascadeLabel();
                refreshCascadeActiveStyles();
            }
            if (tryApplyVolcRequeryPayload()) {
                updateContestCascadeLabel();
                refreshCascadeActiveStyles();
                return;
            }
            var params = new URLSearchParams(window.location.search);
            var qc = params.get('contest');
            if (qc && !_volcRestoredFromSession) setContestSingle(qc, contestNameById(qc));
            var q = params.get('q');
            if (q && !_volcRestoredFromSession) {
                if (welcome && welcome.style.display !== 'none' && welcomeInput) {
                    welcomeInput.value = q;
                } else if (input) {
                    input.value = q;
                }
                setTimeout(function () { volcSend(); }, 450);
                window.history.replaceState({}, '', '/volc-kb');
            }
        }
        function onContestsFailed() {
            if (contestCascadeLabel) contestCascadeLabel.textContent = '获取赛事失败';
            if (tryApplyVolcRequeryPayload()) return;
            try {
                var params = new URLSearchParams(window.location.search);
                var q = params.get('q');
                if (q && !_volcRestoredFromSession) {
                    if (welcome && welcome.style.display !== 'none' && welcomeInput) {
                        welcomeInput.value = q;
                    } else if (input) {
                        input.value = q;
                    }
                    setTimeout(function () { volcSend(); }, 500);
                    window.history.replaceState({}, '', '/volc-kb');
                }
            } catch (e2) {}
        }
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.checkAuth === 'function') {
            window.CR.Auth.checkAuth().then(function (me) {
                var SI = window.CR.Auth.SESSION_INVALID;
                if (me === SI || (me && me.__sessionInvalid)) {
                    try {
                        purgeVolcChatAfterAuthLoss();
                    } catch (e) {}
                    _volcRestoredFromSession = false;
                } else if (localStorage.getItem('token') || _hasCookieToken()) {
                    if (volcHasRequeryPayload()) {
                        try {
                            sessionStorage.removeItem(VOLC_SESSION_KEY);
                        } catch (e) {}
                        _volcRestoredFromSession = false;
                    } else {
                        _volcRestoredFromSession = restoreVolcSession();
                    }
                } else {
                    try {
                        clearVolcSession();
                    } catch (e2) {}
                    _volcRestoredFromSession = false;
                }
                return contestsApi();
            }).then(function (data) {
                onContestsLoaded(data);
            }).catch(function () {
                onContestsFailed();
            });
        } else {
            if (volcHasRequeryPayload()) {
                try {
                    sessionStorage.removeItem(VOLC_SESSION_KEY);
                } catch (e) {}
                _volcRestoredFromSession = false;
            } else {
                _volcRestoredFromSession = restoreVolcSession();
            }
            contestsApi().then(onContestsLoaded).catch(onContestsFailed);
        }
        if (window.CR && window.CR.Api && typeof window.CR.Api.contestsHot === 'function') {
            window.CR.Api.contestsHot(7, 6).then(function (hot) {
                _hotContestsCache = hot;
                applyWelcomeHotTagsPolicy();
            }).catch(function () {
                _hotContestsCache = null;
                if (welcomeTags) welcomeTags.innerHTML = '';
            });
        }
    })();

    var shareBtn = document.getElementById('shareBtn');
    var shareModal = document.getElementById('shareModal');
    var shareModalBackdrop = document.getElementById('shareModalBackdrop');
    var shareModalClose = document.getElementById('shareModalClose');
    var shareModalUrl = document.getElementById('shareModalUrl');
    var shareModalImg = document.getElementById('shareModalImg');
    var shareModalOpen = document.getElementById('shareModalOpen');
    var shareModalCopy = document.getElementById('shareModalCopy');
    var volcLastQuestionId = null;

    function setShareEnabled(on, tip) {
        if (!shareBtn) return;
        shareBtn.disabled = !on;
        if (tip) shareBtn.title = tip;
    }

    function openShareModal(url, previewImg) {
        if (!shareModal) return;
        if (shareModalUrl) shareModalUrl.value = url || '';
        if (shareModalOpen) shareModalOpen.href = url || '#';
        if (shareModalImg) {
            if (previewImg) {
                shareModalImg.src = previewImg;
                shareModalImg.style.display = '';
            } else {
                shareModalImg.removeAttribute('src');
                shareModalImg.style.display = 'none';
            }
        }
        shareModal.classList.add('is-open');
        shareModal.setAttribute('aria-hidden', 'false');
    }

    function closeShareModal() {
        if (!shareModal) return;
        shareModal.classList.remove('is-open');
        shareModal.setAttribute('aria-hidden', 'true');
    }

    if (shareModalBackdrop) shareModalBackdrop.addEventListener('click', closeShareModal);
    if (shareModalClose) shareModalClose.addEventListener('click', closeShareModal);
    if (shareModalCopy && shareModalUrl) {
        shareModalCopy.addEventListener('click', function () {
            var t = shareModalUrl.value || '';
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(t).then(function () {
                    shareModalCopy.textContent = '已复制';
                    setTimeout(function () { shareModalCopy.textContent = '复制'; }, 2000);
                }).catch(function () {
                    shareModalUrl.select();
                    try { document.execCommand('copy'); } catch (e) {}
                });
            } else {
                shareModalUrl.select();
                try { document.execCommand('copy'); } catch (e) {}
            }
        });
    }
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && shareModal && shareModal.classList.contains('is-open')) closeShareModal();
    });

    if (shareBtn) {
        // 初始禁用：需要等本轮问答写入历史拿到 question_id 才可分享
        setShareEnabled(false, '请先完成一次问答后再分享');
        shareBtn.addEventListener('click', function () {
            if (!volcLastQuestionId) {
                setShareEnabled(false, '请先完成一次问答后再分享');
                return;
            }
            if (!window.axios) return;
            setShareEnabled(false, '正在生成分享链接…');
            window.axios.post('/api/share', { question_id: volcLastQuestionId }).then(function (res) {
                var j = res && res.data ? res.data : null;
                if (!j || j.code !== 0 || !j.data || !j.data.url) {
                    throw new Error((j && j.message) || '生成分享失败');
                }
                openShareModal(j.data.url, j.data.preview_image || '');
                setShareEnabled(true, '分享当前这条问答');
            }).catch(function (e) {
                setShareEnabled(true, '生成分享失败，可重试');
                try {
                    addVolcMsg('assistant', '生成分享链接失败：' + ((e && e.message) || '未知错误'), true);
                } catch (e2) {}
            });
        });
    }

    if (sendBtn) sendBtn.addEventListener('click', function () { onVolcComposerPrimaryAction(); });
    if (input) {
        input.addEventListener('input', function () { syncVolcComposerButtons(); });
        input.addEventListener('keydown', onVolcComposerKeydown);
    }

    if (welcomeSendBtn) {
        welcomeSendBtn.addEventListener('click', function () { onVolcComposerPrimaryAction(); });
    }
    if (welcomeInput) {
        welcomeInput.addEventListener('input', function () { syncVolcComposerButtons(); });
        welcomeInput.addEventListener('keydown', onVolcComposerKeydown);
    }

    syncVolcComposerButtons();

    var welcomePlaceholderDefault = '尽管问...';
    var welcomePlaceholderOpen = '可自由描述您的问题，不限于固定模板…';

    document.querySelectorAll('.func-btn:not(.volc-kb-attach-btn)').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var wrap = btn.closest('.welcome-input-wrap');
            var ta = wrap ? wrap.querySelector('textarea') : null;
            if (!ta) return;
            var query = (btn.getAttribute('data-query') || '').trim();
            var isOpen = btn.getAttribute('data-func') === 'open';
            document.querySelectorAll('.func-btn:not(.volc-kb-attach-btn)').forEach(function (b) {
                b.classList.remove('is-active');
                if (isOpen && b.getAttribute('data-func') === 'open') b.classList.add('is-active');
                else if (!isOpen && query && b.getAttribute('data-query') === query) b.classList.add('is-active');
            });

            if (isOpen) {
                ta.value = '';
                ta.placeholder = welcomePlaceholderOpen;
            } else if (query) {
                ta.value = '';
                ta.placeholder = query;
            }
            ta.focus();
        });
    });

    document.querySelector('[data-id="new"]')?.addEventListener('click', function () {
        try {
            volcAbortInFlight();
        } catch (e0) {}
        try {
            clearVolcSession();
        } catch (e) {}
        volcHistory = [];
        var bubbles = chatArea.querySelectorAll('.chat-bubble');
        bubbles.forEach(function (el) { el.remove(); });
        switchToWelcomeMode();
        setContestAll();
        if (welcomeInput) {
            welcomeInput.value = '';
            welcomeInput.placeholder = welcomePlaceholderDefault;
        }
        if (input) {
            input.value = '';
            input.placeholder = '输入问题...';
        }
        clearVolcUploads();
        document.querySelectorAll('.func-btn:not(.volc-kb-attach-btn)').forEach(function (b) { b.classList.remove('is-active'); });
        applyWelcomeHotTagsPolicy();
    });

})();
