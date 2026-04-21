(function () {
    // 首页始终进入问答页；未登录则禁用发送并提示“请先登录”
    const un = document.getElementById('username');
    function _hasCookieToken() {
        try {
            return document.cookie.split(';').some(function (c) { return c.trim().startsWith('token='); });
        } catch (e) {
            return false;
        }
    }

    function _isLoggedInForUi() {
        // UI 上严格按“有效登录态”显示用户名，避免 localStorage 残留 username 误导
        const hasToken = !!localStorage.getItem('token');
        const hasUserId = !!localStorage.getItem('user_id');
        if (hasToken && hasUserId) return true;
        // 仅有 cookie（例如页面路由场景）时，也不显示具体用户名（因为前端不知道是谁）
        return false;
    }

    if (un) {
        un.textContent = _isLoggedInForUi()
            ? (localStorage.getItem('username') || '用户')
            : '游客';
    }

    // 以服务端 /api/auth/me 为准纠正 UI（解决本地残留导致“未登录却显示 admin”）
    (function syncMeToUi() {
        if (!(window.CR && window.CR.Auth && typeof window.CR.Auth.checkAuth === 'function') || !un) return;
        var SI = window.CR.Auth.SESSION_INVALID;
        window.CR.Auth.checkAuth().then(function (me) {
            if (me === SI || (me && me.__sessionInvalid)) {
                if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
                    try { window.CR.Auth.clearAuth(); } catch (e) {}
                }
                un.textContent = '游客';
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
            if (typeof updateShareBtnState === 'function') updateShareBtnState();
            if (typeof applyWelcomeHotTagsPolicy === 'function') applyWelcomeHotTagsPolicy();
        });
    })();
    document.getElementById('logout')?.addEventListener('click', function(e) {
        e.preventDefault();
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

    if (inputBar) inputBar.style.display = 'none';

    let deepThinkEnabled = false;
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
        window.location.href = '/login?next=' + encodeURIComponent('/graphrag');
    }

    function requireLoginGuard() {
        const hasToken = !!localStorage.getItem('token');
        if (!hasToken && !_hasCookieToken()) {
            addMsg('assistant', '请先登录！', true);
            showLoginTipAndGo();
            return false;
        }
        return true;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function nl2br(text) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function renderMarkdown(md) {
        // 轻量 Markdown 渲染（满足本项目输出格式：标题/列表/加粗/段落）
        // 说明：不支持任意 HTML，先 escape 再做有限替换，避免 XSS。
        // 支持：标题/列表/加粗/分隔线/表格（pipe table）。
        md = (md == null) ? '' : String(md);
        const lines = md.replace(/\r\n/g, '\n').split('\n');
        let html = '';
        let inList = false;
        let inTable = false;
        let tableHeader = null; // array<string>
        let tableRows = []; // array<array<string>>

        function closeList() {
            if (inList) {
                html += '</ul>';
                inList = false;
            }
        }

        function _isTableRow(t) {
            // must contain at least 2 pipes, and not be just a single '|' char
            const s = String(t || '');
            const pipeCount = (s.match(/\|/g) || []).length;
            return pipeCount >= 2;
        }

        function _isTableSepRow(t) {
            // e.g. | --- | --- | or ---|:---:|---:
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
            // render table
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
                // no header; still render
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
            // **bold**
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

            // headings
            if (t.startsWith('# ')) { closeTable(); closeList(); html += '<h1>' + inlineFormat(t.slice(2)) + '</h1>'; continue; }
            if (t.startsWith('#### ')) { closeTable(); closeList(); html += '<h4>' + inlineFormat(t.slice(5)) + '</h4>'; continue; }
            if (t.startsWith('### ')) { closeTable(); closeList(); html += '<h3>' + inlineFormat(t.slice(4)) + '</h3>'; continue; }
            if (t.startsWith('## ')) { closeTable(); closeList(); html += '<h2>' + inlineFormat(t.slice(3)) + '</h2>'; continue; }

            // hr
            if (t === '---') { closeTable(); closeList(); html += '<hr>'; continue; }

            // list item: "- xxx"
            if (t.startsWith('- ')) {
                closeTable();
                if (!inList) { html += '<ul>'; inList = true; }
                html += '<li>' + inlineFormat(t.slice(2)) + '</li>';
                continue;
            }

            // table: header row + sep row + body rows
            if (_isTableRow(t)) {
                // starting table: current line is header, next non-empty line is sep
                if (!inTable) {
                    // lookahead for sep row
                    let j = i + 1;
                    while (j < lines.length && !String(lines[j] || '').trim()) j++;
                    const next = j < lines.length ? String(lines[j] || '').trim() : '';
                    if (next && _isTableSepRow(next)) {
                        closeList();
                        inTable = true;
                        tableHeader = _parseTableCells(t);
                        tableRows = [];
                        // skip sep row
                        i = j;
                        continue;
                    }
                } else {
                    // in table body
                    if (_isTableSepRow(t)) {
                        continue;
                    }
                    tableRows.push(_parseTableCells(t));
                    continue;
                }
            }

            // normal paragraph
            closeTable();
            closeList();
            html += '<p>' + inlineFormat(t) + '</p>';
        }
        closeTable();
        closeList();
        return html || '<p></p>';
    }

    function _parseContestIdFromRefFile(file) {
        // 约定：图片文件名形如 "<contest_id>_<page>.jpg"
        // 例如 "20_“华为杯”第二十一届..._2.jpg" → contest_id="20_“华为杯”第二十一届..."
        try {
            var base = String(file || '');
            if (!base) return '';
            base = base.split('?')[0];
            // 去扩展名
            if (base.indexOf('.') >= 0) base = base.slice(0, base.lastIndexOf('.'));
            var parts = base.split('_');
            if (parts.length >= 2 && /^\d+$/.test(parts[parts.length - 1])) {
                parts.pop();
                return parts.join('_');
            }
            return base;
        } catch (e) {
            return '';
        }
    }

    function _contestNameById(contestId) {
        // 优先用 /api/contests 里的人类可读赛事名；拿不到就回退到 id
        try {
            var cid = String(contestId || '').trim();
            if (!cid) return '';
            for (var i = 0; i < (contestList || []).length; i++) {
                var c = contestList[i];
                if (!c) continue;
                if (String(c.id || '').trim() === cid) return String(c.name || c.id || cid);
            }
            return cid;
        } catch (e) {
            return String(contestId || '');
        }
    }

    function imageRefsToUrls(imageRefs, imageDataset) {
        if (!Array.isArray(imageRefs) || imageRefs.length === 0) return [];
        const base = typeof window.API_BASE !== 'undefined' ? window.API_BASE : '';
        const token = localStorage.getItem('token');
        const q = token ? '?token=' + encodeURIComponent(token) : '';
        return imageRefs.map(function (ref) {
            var fallbackUrl = base + '/api/img/' + encodeURIComponent(imageDataset || '') + '/' + encodeURIComponent(ref.file) + q;
            var url = ref.url
                ? ref.url
                : fallbackUrl;
            var contestId = ref.contest_id || ref.competition_id || _parseContestIdFromRefFile(ref.file);
            var contestName = ref.contest_name || _contestNameById(contestId);
            return {
                url: url,
                fallback_url: fallbackUrl,
                page: ref.page != null ? ref.page : 1,
                contest_id: contestId,
                contest_name: contestName
            };
        });
    }

    // ---------------- 图片预览器（多图切换 / 关闭 / 下载） ----------------
    const viewerEl = document.getElementById('imgViewer');
    const viewerImgEl = document.getElementById('imgViewerImg');
    const viewerMetaEl = document.getElementById('imgViewerMeta');
    const viewerCloseEl = document.getElementById('imgViewerClose');
    const viewerPrevEl = document.getElementById('imgViewerPrev');
    const viewerNextEl = document.getElementById('imgViewerNext');
    const viewerDownloadEl = document.getElementById('imgViewerDownload');

    let _viewerList = [];
    let _viewerIndex = 0;

    // ---------------- 轻量提示（下载中/成功/失败） ----------------
    let _toastTimer = null;
    function toast(msg, kind, ms) {
        try {
            ms = ms == null ? 2200 : ms;
            kind = kind || 'info';
            let el = document.getElementById('crToast');
            if (!el) {
                el = document.createElement('div');
                el.id = 'crToast';
                el.setAttribute('role', 'status');
                el.setAttribute('aria-live', 'polite');
                // 不依赖 CSS 文件，避免改动面扩大
                el.style.position = 'fixed';
                el.style.left = '50%';
                el.style.bottom = '20px';
                el.style.transform = 'translateX(-50%)';
                el.style.zIndex = '9999';
                el.style.maxWidth = '92vw';
                el.style.padding = '10px 12px';
                el.style.borderRadius = '10px';
                el.style.fontSize = '13px';
                el.style.lineHeight = '1.4';
                el.style.boxShadow = '0 10px 30px rgba(0,0,0,.16)';
                el.style.backdropFilter = 'blur(8px)';
                el.style.display = 'none';
                document.body.appendChild(el);
            }
            if (kind === 'error') {
                el.style.background = 'rgba(220, 53, 69, 0.95)';
                el.style.color = '#fff';
            } else if (kind === 'success') {
                el.style.background = 'rgba(40, 167, 69, 0.95)';
                el.style.color = '#fff';
            } else {
                el.style.background = 'rgba(33, 37, 41, 0.92)';
                el.style.color = '#fff';
            }
            el.textContent = String(msg || '');
            el.style.display = 'block';
            if (_toastTimer) clearTimeout(_toastTimer);
            _toastTimer = setTimeout(function () {
                try { el.style.display = 'none'; } catch (e) {}
            }, ms);
        } catch (e) {}
    }

    function _safeFilename(s) {
        s = String(s || '').trim();
        if (!s) return 'page';
        // 替换掉常见文件名非法字符
        return s.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80);
    }

    async function _downloadImageWithFeedback(item) {
        if (!item || !item.url) return;
        const cname = item.contest_name || item.contest_id || 'page';
        const p = item.page || (_viewerIndex + 1);
        const filename = _safeFilename(cname) + '_p' + String(p) + '.jpg';

        toast('下载中…（将保存到浏览器默认下载目录）', 'info', 1600);
        try {
            // 优先 fetch -> blob 触发下载，避免跨域时 download 属性被浏览器忽略导致“跳转”
            const resp = await fetch(item.url, { mode: 'cors', credentials: 'omit' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const blob = await resp.blob();
            const objUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () {
                try { URL.revokeObjectURL(objUrl); } catch (e) {}
            }, 10_000);
            toast('已触发下载：' + filename, 'success', 2200);
        } catch (e) {
            // 常见原因：OSS 未开 CORS/跨域限制/浏览器策略
            toast('下载失败（可能是跨域限制），已为你打开图片链接。', 'error', 2600);
            try { window.open(item.url, '_blank', 'noopener'); } catch (e2) { window.location.href = item.url; }
        }
    }

    function _viewerMetaText(item, state) {
        var cname = (item && (item.contest_name || item.contest_id)) ? (item.contest_name || item.contest_id) : '';
        var p = (item && item.page) ? item.page : (_viewerIndex + 1);
        var base = `${cname ? (cname + ' ') : ''}第 ${p} 页（${_viewerIndex + 1}/${_viewerList.length || 1}）`;
        if (state === 'loading') return base + ' · 正在加载图片…';
        if (state === 'error') return base + ' · 图片加载失败';
        return base;
    }

    function _viewerSet(idx) {
        if (!_viewerList || _viewerList.length === 0) return;
        _viewerIndex = (idx + _viewerList.length) % _viewerList.length;
        const item = _viewerList[_viewerIndex];
        if (!item) return;

        // 先挂载 load/error，再设置 src（避免缓存命中时事件丢失）
        try {
            viewerImgEl.onload = null;
            viewerImgEl.onerror = null;
        } catch (e) {}
        if (viewerMetaEl) viewerMetaEl.textContent = _viewerMetaText(item, 'loading');

        try {
            viewerImgEl.onload = function () {
                try { if (viewerMetaEl) viewerMetaEl.textContent = _viewerMetaText(item, 'loaded'); } catch (e) {}
            };
            viewerImgEl.onerror = function () {
                try { if (viewerMetaEl) viewerMetaEl.textContent = _viewerMetaText(item, 'error'); } catch (e) {}
            };
        } catch (e) {}

        viewerImgEl.src = item.url;
        viewerDownloadEl.href = item.url;
        viewerDownloadEl.setAttribute('download', `page_${item.page || (_viewerIndex + 1)}.jpg`);
    }

    function openImageViewer(list, idx) {
        if (!viewerEl || !viewerImgEl) return;
        _viewerList = Array.isArray(list) ? list.slice() : [];
        if (_viewerList.length === 0) return;
        viewerEl.classList.add('is-open');
        viewerEl.setAttribute('aria-hidden', 'false');
        _viewerSet(idx || 0);
    }

    function closeImageViewer() {
        if (!viewerEl) return;
        viewerEl.classList.remove('is-open');
        viewerEl.setAttribute('aria-hidden', 'true');
        // 不要设置 src=''，部分浏览器会把它解析为当前页面 URL（导致 img 加载 / 触发 resource.load.error）
        try { if (viewerImgEl) viewerImgEl.removeAttribute('src'); } catch (e) {}
        _viewerList = [];
        _viewerIndex = 0;
    }

    if (viewerCloseEl) viewerCloseEl.addEventListener('click', closeImageViewer);
    if (viewerPrevEl) viewerPrevEl.addEventListener('click', function () { _viewerSet(_viewerIndex - 1); });
    if (viewerNextEl) viewerNextEl.addEventListener('click', function () { _viewerSet(_viewerIndex + 1); });
    if (viewerDownloadEl) {
        viewerDownloadEl.addEventListener('click', function (e) {
            try { e.preventDefault(); } catch (e0) {}
            const item = (_viewerList && _viewerList.length) ? _viewerList[_viewerIndex] : null;
            _downloadImageWithFeedback(item);
        });
    }
    if (viewerEl) {
        viewerEl.addEventListener('click', function (e) {
            // 点击遮罩背景关闭（不影响面板内部点击）
            if (e.target === viewerEl) closeImageViewer();
        });
    }
    document.addEventListener('keydown', function (e) {
        if (!viewerEl || !viewerEl.classList.contains('is-open')) return;
        if (e.key === 'Escape') closeImageViewer();
        else if (e.key === 'ArrowLeft') _viewerSet(_viewerIndex - 1);
        else if (e.key === 'ArrowRight') _viewerSet(_viewerIndex + 1);
    });

    function engineLabel(src) {
        if (src === 'vidorag') return 'Vidorag 视觉检索';
        if (src === 'graphrag') return 'GraphRAG 知识图谱';
        if (src === 'hybrid') return '双引擎融合';
        if (src === 'structured') return '结构化数据';
        if (src === 'structured_kb') return '结构化知识库';
        if (src === 'llm') return 'LLM 直答';
        return '';
    }
    function engineClass(src) {
        if (src === 'vidorag') return 'engine-vidorag';
        if (src === 'graphrag') return 'engine-graphrag';
        if (src === 'hybrid') return 'engine-hybrid';
        if (src === 'structured') return 'engine-structured';
        if (src === 'structured_kb') return 'engine-structured';
        if (src === 'llm') return 'engine-llm';
        return '';
    }

    function switchToChatMode() {
        if (welcome) welcome.style.display = 'none';
        if (inputBar) inputBar.style.display = '';
    }

    function switchToWelcomeMode() {
        if (welcome) welcome.style.display = '';
        if (inputBar) inputBar.style.display = 'none';
    }

    // ---------------- 小范围预加载（图片依据） ----------------
    // 目标：/api/chat 返回后立刻预热 4~5 张引用页图，降低打开“图片依据”时的延迟。
    const _preloadCache = new Map(); // url -> Promise<void>
    function _preloadOne(url, timeoutMs) {
        try {
            url = String(url || '').trim();
            if (!url) return Promise.resolve();
            if (_preloadCache.has(url)) return _preloadCache.get(url);
            const p = new Promise(function (resolve) {
                const img = new Image();
                let done = false;
                const t = setTimeout(function () {
                    if (done) return;
                    done = true;
                    try { img.onload = null; img.onerror = null; } catch (e) {}
                    resolve();
                }, timeoutMs || 8000);
                img.onload = function () {
                    if (done) return;
                    done = true;
                    clearTimeout(t);
                    resolve();
                };
                img.onerror = function () {
                    if (done) return;
                    done = true;
                    clearTimeout(t);
                    resolve();
                };
                // 触发下载进缓存
                img.src = url;
            });
            _preloadCache.set(url, p);
            return p;
        } catch (e) {
            return Promise.resolve();
        }
    }

    function _preloadRefs(refs) {
        try {
            if (!Array.isArray(refs) || refs.length === 0) return;
            // 一般就 3~5 张，限制到 6 防止极端情况
            const list = refs.slice(0, 6);
            // 先预加载主 url；失败时也会走 error->fallback 的加载，但我们也提前预热 fallback_url
            list.forEach(function (r) {
                _preloadOne(r && r.url, 8000);
                if (r && r.fallback_url) _preloadOne(r.fallback_url, 8000);
            });
        } catch (e) {}
    }

    function addMsg(role, content, isError, imageRefs, imageDataset, engineSource, queryType) {
        switchToChatMode();
        const bubble = document.createElement('div');
        var bubbleExtra = '';
        if (isError === true) bubbleExtra = ' error';
        else if (isError === 'interrupt') bubbleExtra = ' interrupt';
        bubble.className = 'chat-bubble ' + role + bubbleExtra;
        const title = role === 'user' ? '我' : (isError === 'interrupt' ? '提示' : '智能竞赛客服机器人');

        var metaHtml = '';
        if (role === 'assistant' && engineSource && isError !== 'interrupt') {
            metaHtml = '<div class="answer-meta">'
                + '<span class="engine-tag ' + engineClass(engineSource) + '">' + engineLabel(engineSource) + '</span>'
                + (queryType ? '<span class="type-tag">' + (queryType === 'visual' ? '视觉类' : (queryType === 'chitchat' ? '闲聊类' : '纯文类')) + '</span>' : '')
                + '</div>';
        }

        const bodyHtml = (role === 'assistant')
            ? renderMarkdown(content)
            : ('<p>' + nl2br(content) + '</p>');

        bubble.innerHTML =
            '<div class="chat-title">' + escapeHtml(title) + '</div>' +
            metaHtml +
            '<div class="chat-content">' + bodyHtml + '</div>';
        if (role === 'assistant' && imageRefs && imageRefs.length > 0) {
            const refs = imageRefsToUrls(imageRefs, imageDataset);
            if (refs.length > 0) {
                // 预加载：在 DOM 渲染前就开始“悄悄下载”，等用户点开右侧图片依据时更快
                _preloadRefs(refs);

                const chatContentEl = bubble.querySelector('.chat-content');
                if (!chatContentEl) {
                    chatArea.appendChild(bubble);
                    chatArea.scrollTop = chatArea.scrollHeight;
                    return;
                }

                const leftEl = document.createElement('div');
                leftEl.className = 'answer-left';
                leftEl.innerHTML = '<div class="answer-text">' + bodyHtml + '</div>';

                const toggleBtn = document.createElement('button');
                toggleBtn.type = 'button';
                toggleBtn.className = 'img-toggle-btn';
                toggleBtn.textContent = '查看图片依据 🖼️';
                leftEl.appendChild(toggleBtn);

                const rightEl = document.createElement('div');
                rightEl.className = 'answer-right';
                rightEl.setAttribute('aria-hidden', 'true');

                const block = document.createElement('div');
                block.className = 'answer-ref-pages';
                block.innerHTML = '<div class="answer-ref-title">回答所基于的 PDF 页码</div>';

                const row = document.createElement('div');
                row.className = 'answer-ref-row';
                refs.forEach(function (r, idx) {
                    const cell = document.createElement('div');
                    cell.className = 'answer-ref-cell';
                    cell.style.position = 'relative';
                    // 预加载/弱网时，img 还没出尺寸会导致 cell 高度塌陷，绝对定位占位层互相覆盖；
                    // 这里给缩略图一个固定的展示框，确保布局稳定。
                    cell.style.width = '160px';
                    const img = document.createElement('img');
                    img.src = r.url;
                    img.alt = (r.contest_name || r.contest_id ? (String(r.contest_name || r.contest_id) + ' ') : '') + '第' + r.page + '页';
                    // 依据页图数量很少：统一 eager + 预加载，提升首屏体验
                    img.loading = 'eager';
                    try { img.decoding = 'async'; } catch (e) {}
                    img.style.cursor = 'zoom-in';
                    img.style.width = '160px';
                    img.style.height = '120px';
                    img.style.objectFit = 'cover';
                    img.style.display = 'block';

                    // 缩略图加载占位（网络/OSS 延迟时更友好）
                    const ph = document.createElement('div');
                    ph.className = 'answer-ref-placeholder';
                    ph.textContent = '图片加载中…';
                    ph.style.position = 'absolute';
                    ph.style.left = '8px';
                    ph.style.right = '8px';
                    ph.style.top = '8px';
                    ph.style.height = '120px';
                    ph.style.display = 'flex';
                    ph.style.alignItems = 'center';
                    ph.style.justifyContent = 'center';
                    ph.style.fontSize = '12px';
                    ph.style.color = '#6b7280';
                    ph.style.background = 'linear-gradient(135deg, rgba(245,246,248,.95), rgba(238,240,244,.95))';
                    ph.style.border = '1px dashed rgba(180,185,195,.9)';
                    ph.style.borderRadius = '10px';
                    ph.style.pointerEvents = 'none';

                    function _phHide() { try { ph.style.display = 'none'; } catch (e) {} }
                    function _phError() {
                        try {
                            ph.textContent = '图片加载失败';
                            ph.style.borderStyle = 'solid';
                            ph.style.borderColor = 'rgba(220,53,69,.55)';
                            ph.style.color = '#b42318';
                        } catch (e) {}
                    }

                    img.addEventListener('load', _phHide);
                    // OSS 直链偶发不可达/被拦截时，自动回退到本地代理下载（/api/img）
                    img.addEventListener('error', function () {
                        try {
                            if (img.__crFallbackTried) return;
                            img.__crFallbackTried = true;
                            if (r && r.fallback_url && img.src !== r.fallback_url) {
                                img.src = r.fallback_url;
                                // 继续等待 fallback 加载；不在这里标错
                                return;
                            }
                        } catch (e) {}
                        _phError();
                    });
                    img.addEventListener('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        openImageViewer(refs, idx);
                    });
                    const span = document.createElement('span');
                    span.className = 'answer-ref-page';
                    var contestLabel = String(r.contest_name || r.contest_id || '').trim();
                    span.textContent = (contestLabel ? ('【' + contestLabel + '】') : '') + '第 ' + r.page + ' 页';
                    cell.appendChild(ph);
                    cell.appendChild(img);
                    cell.appendChild(span);
                    row.appendChild(cell);
                });
                block.appendChild(row);
                rightEl.appendChild(block);

                const wrapper = document.createElement('div');
                wrapper.className = 'answer-wrapper';
                wrapper.appendChild(leftEl);
                wrapper.appendChild(rightEl);

                toggleBtn.addEventListener('click', function () {
                    var isShow = rightEl.classList.toggle('show');
                    rightEl.setAttribute('aria-hidden', isShow ? 'false' : 'true');
                    toggleBtn.textContent = isShow ? '收起图片依据 ▲' : '查看图片依据 🖼️';
                });

                chatContentEl.innerHTML = '';
                chatContentEl.appendChild(wrapper);
            }
        }
        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function addLoading() {
        switchToChatMode();
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble assistant';
        bubble.innerHTML =
            '<div class="chat-title">智能竞赛客服机器人</div>' +
            '<div class="chat-content"><span class="loading">正在思考中…</span> <span class="loading-elapsed" style="opacity:.7;"></span></div>';
        chatArea.appendChild(bubble);
        chatArea.scrollTop = chatArea.scrollHeight;

        // 显示耗时（纯前端 UI，不影响接口）
        try {
            const start = Date.now();
            const el = bubble.querySelector('.loading-elapsed');
            if (el) {
                const timer = setInterval(function () {
                    const sec = Math.max(0, Math.floor((Date.now() - start) / 1000));
                    el.textContent = sec ? ('已等待 ' + sec + 's') : '';
                }, 500);
                bubble.__crTimer = timer;
            }
        } catch (e) {}
        return bubble;
    }

    const contestCascade = document.getElementById('contestCascade');
    const contestCascadeBtn = document.getElementById('contestCascadeBtn');
    const contestCascadeDropdown = document.getElementById('contestCascadeDropdown');
    const contestCascadeLabel = document.getElementById('contestCascadeLabel');
    const contestCascadeCats = document.getElementById('contestCascadeCats');
    const contestCascadeItems = document.getElementById('contestCascadeItems');
    const contestCascadeAllInCat = document.getElementById('contestCascadeAllInCat');
    const contestCascadeRightTitle = document.getElementById('contestCascadeRightTitle');
    const welcomeTags = document.getElementById('welcomeTags');
    /** 热门赛事接口缓存：仅未登录且在欢迎页时渲染到 #welcomeTags；已登录或已进入对话后不展示 */
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

    function getContestScopeIds() {
        if (contestSelection.mode === 'all') return null;
        if (contestSelection.mode === 'single' && contestSelection.id) return [contestSelection.id];
        if (contestSelection.mode === 'category' && Array.isArray(contestSelection.ids) && contestSelection.ids.length) {
            return contestSelection.ids.slice();
        }
        return null;
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

    (function loadContests() {
        contestsApi().then(function (data) {
            initContestCascadeUi(data);
            var params = new URLSearchParams(window.location.search);
            var qc = params.get('contest');
            if (qc) setContestSingle(qc, contestNameById(qc));
            var q = params.get('q');
            if (q) {
                if (input) input.value = q;
                setTimeout(function () { send(); }, 450);
                window.history.replaceState({}, '', '/graphrag');
            }
        }).catch(function () {
            if (contestCascadeLabel) contestCascadeLabel.textContent = '获取赛事失败';
            try {
                var params = new URLSearchParams(window.location.search);
                var q = params.get('q');
                if (q && input) {
                    input.value = q;
                    setTimeout(function () { send(); }, 500);
                    window.history.replaceState({}, '', '/graphrag');
                }
            } catch (e2) {}
        });
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

    function updateShareBtnState() {
        if (!shareBtn) return;
        var logged = !!(localStorage.getItem('token') && localStorage.getItem('user_id'));
        shareBtn.disabled = !logged || !lastQuestionId;
        shareBtn.title = !logged
            ? '请先登录后分享'
            : (!lastQuestionId ? '先完成一轮对话后再分享' : '分享本轮问答');
    }

    function openShareModal(payload) {
        if (!shareModal || !shareModalUrl) return;
        var url = (payload && payload.url) || '';
        shareModalUrl.value = url;
        if (shareModalOpen) shareModalOpen.href = url || '#';
        if (shareModalImg) {
            if (payload && payload.preview_image) {
                shareModalImg.src = payload.preview_image;
                shareModalImg.style.display = '';
                shareModalImg.onerror = function () {
                    shareModalImg.style.display = 'none';
                };
            } else {
                shareModalImg.style.display = 'none';
                try { shareModalImg.removeAttribute('src'); } catch (e) {}
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

    if (shareBtn && window.CR && window.CR.Api && typeof window.CR.Api.createShare === 'function') {
        shareBtn.addEventListener('click', function () {
            if (!lastQuestionId) return;
            if (!(localStorage.getItem('token') && localStorage.getItem('user_id'))) {
                showLoginTipAndGo();
                return;
            }
            window.CR.Api.createShare(lastQuestionId).then(function (j) {
                var d = j.data || {};
                openShareModal({ url: d.url, preview_image: d.preview_image });
            }).catch(function (e) {
                alert(e.message || '分享失败');
            });
        });
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

    updateShareBtnState();

    let chatHistory = [];
    /** 最近一轮已成功落库的问答 ID（用于分享） */
    var lastQuestionId = null;
    var pendingRequestId = null;
    var pendingAbortController = null;
    var pendingLoadingEl = null;
    var _sendBtnDefaultText = null;
    var _welcomeBtnDefaultText = null;

    function _setSendButtonState(isRunning) {
        if (_sendBtnDefaultText == null && sendBtn) _sendBtnDefaultText = sendBtn.textContent;
        if (_welcomeBtnDefaultText == null && welcomeSendBtn) _welcomeBtnDefaultText = welcomeSendBtn.textContent;

        // 运行中：按钮可点击，含义为“中断并发送”
        if (sendBtn) {
            sendBtn.classList.toggle('is-running', !!isRunning);
            sendBtn.title = isRunning ? '中断当前回答并发送新问题' : '发送';
            sendBtn.textContent = isRunning ? '⏹' : (_sendBtnDefaultText || '➤');
        }
        if (welcomeSendBtn) {
            welcomeSendBtn.classList.toggle('is-running', !!isRunning);
            welcomeSendBtn.title = isRunning ? '中断当前回答并发送新问题' : '发送';
            welcomeSendBtn.textContent = isRunning ? '⏹' : (_welcomeBtnDefaultText || '➤');
        }
    }

    async function send(msgOverride) {
        if (!requireLoginGuard()) return;
        var msg = msgOverride || (input ? input.value.trim() : '');
        if (!msg && welcomeInput) msg = welcomeInput.value.trim();

        // 运行中且未输入新内容就点 ⏹：只中断当前请求（原先在 !msg 处提前 return，导致永远不执行 abort）
        if (!msg && pendingAbortController) {
            var ridStop = pendingRequestId;
            try {
                pendingAbortController.abort();
            } catch (e) {}
            if (pendingLoadingEl) {
                try { if (pendingLoadingEl.__crTimer) clearInterval(pendingLoadingEl.__crTimer); } catch (e) {}
                pendingLoadingEl.remove();
            }
            pendingLoadingEl = null;
            pendingAbortController = null;
            pendingRequestId = null;
            _setSendButtonState(false);
            if (ridStop && window.CR && window.CR.Api && typeof window.CR.Api.chatCancel === 'function') {
                try {
                    await window.CR.Api.chatCancel(ridStop);
                } catch (e) {}
            }
            return;
        }

        if (!msg) return;
        input.value = '';
        if (welcomeInput) welcomeInput.value = '';

        if (pendingAbortController) {
            pendingAbortController.abort();
            if (pendingLoadingEl) {
                try { if (pendingLoadingEl.__crTimer) clearInterval(pendingLoadingEl.__crTimer); } catch (e) {}
                pendingLoadingEl.remove();
            }
        }
        var cancelRequestId = pendingRequestId || null;
        var thisRequestId = 'req-' + Date.now() + '-' + Math.random().toString(36).slice(2);
        pendingRequestId = thisRequestId;
        pendingAbortController = new AbortController();
        addMsg('user', msg);
        if (cancelRequestId) {
            addMsg('assistant', '已中断上一轮回答', 'interrupt');
        }
        pendingLoadingEl = addLoading();
        _setSendButtonState(true);
        try {
            const res = await chatApi(msg, chatHistory, thisRequestId, null, {
                signal: pendingAbortController.signal,
                cancelRequestId: cancelRequestId,
                deep_think: deepThinkEnabled,
                contest_ids: getContestScopeIds(),
            });
            if (pendingRequestId !== thisRequestId) {
                return;
            }
            if (pendingLoadingEl) {
                try { if (pendingLoadingEl.__crTimer) clearInterval(pendingLoadingEl.__crTimer); } catch (e) {}
                pendingLoadingEl.remove();
            }
            pendingLoadingEl = null;
            if (res && res.status === 'cancelled') {
                var cancelText = (res.answer && String(res.answer).trim()) || '已中断上一轮回答';
                if (!cancelRequestId) {
                    addMsg('assistant', cancelText, 'interrupt');
                }
                return;
            }
            addMsg(
                'assistant',
                res.answer || '无回复',
                false,
                res.image_refs,
                res.image_dataset,
                res.engine_source,
                res.query_type
            );
            if (Array.isArray(res.history)) chatHistory = res.history;
            if (res.question_id != null) {
                lastQuestionId = res.question_id;
                updateShareBtnState();
            }
        } catch (e) {
            if (e.name === 'AbortError') {
                if (pendingLoadingEl && pendingRequestId === thisRequestId) {
                    try { if (pendingLoadingEl.__crTimer) clearInterval(pendingLoadingEl.__crTimer); } catch (e2) {}
                    pendingLoadingEl.remove();
                }
                return;
            }
            if (pendingRequestId !== thisRequestId) {
                return;
            }
            if (pendingLoadingEl) {
                try { if (pendingLoadingEl.__crTimer) clearInterval(pendingLoadingEl.__crTimer); } catch (e2) {}
                pendingLoadingEl.remove();
            }
            var errMsg = (e && e.message) ? String(e.message) : '未知错误';
            if (errMsg.indexOf('cancelled') >= 0 || errMsg.indexOf('中断') >= 0) {
                addMsg('assistant', '已中断上一轮回答', 'interrupt');
            } else {
                addMsg('assistant', '请求失败: ' + errMsg, true);
            }
        } finally {
            if (pendingRequestId === thisRequestId) {
                pendingRequestId = null;
                pendingAbortController = null;
                pendingLoadingEl = null;
                _setSendButtonState(false);
            }
        }
    }

    sendBtn.addEventListener('click', function () { send(); });
    if (input) {
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        });
    }

    if (welcomeSendBtn) {
        welcomeSendBtn.addEventListener('click', function () { send(); });
    }
    if (welcomeInput) {
        welcomeInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        });
    }

    var welcomePlaceholderDefault = '尽管问...';
    var welcomePlaceholderOpen = '可自由描述您的问题，不限于固定模板…';

    document.querySelectorAll('.func-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var wrap = btn.closest('.welcome-input-wrap');
            var ta = wrap ? wrap.querySelector('textarea') : null;
            if (!ta) return;
            var query = (btn.getAttribute('data-query') || '').trim();
            var isOpen = btn.getAttribute('data-func') === 'open';
            document.querySelectorAll('.func-btn').forEach(function (b) {
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
        chatHistory = [];
        lastQuestionId = null;
        updateShareBtnState();
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
        document.querySelectorAll('.func-btn').forEach(function (b) { b.classList.remove('is-active'); });
    });

})();
