(function () {
    if (!localStorage.getItem('token')) {
        window.location.href = '/login?next=/history';
        return;
    }

    document.getElementById('logout')?.addEventListener('click', function (e) {
        e.preventDefault();
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
            try { window.CR.Auth.clearAuth(); } catch (e) {}
        } else {
            localStorage.removeItem('token');
            localStorage.removeItem('username');
            localStorage.removeItem('user_id');
            localStorage.removeItem('is_admin');
            document.cookie = 'token=; Path=/; Max-Age=0; SameSite=Lax';
        }
        window.location.href = '/login';
    });

    var currentPage = 0;
    var pageSize = 20;
    var totalCount = 0;
    var currentDetailId = null;
    // 图片预览器（复用问答页交互）
    const viewerEl = document.getElementById('imgViewer');
    const viewerImgEl = document.getElementById('imgViewerImg');
    const viewerMetaEl = document.getElementById('imgViewerMeta');
    const viewerCloseEl = document.getElementById('imgViewerClose');
    const viewerPrevEl = document.getElementById('imgViewerPrev');
    const viewerNextEl = document.getElementById('imgViewerNext');
    const viewerDownloadEl = document.getElementById('imgViewerDownload');
    let _viewerList = [];
    let _viewerIndex = 0;

    function escapeHtml(t) {
        var d = document.createElement('div');
        d.textContent = t;
        return d.innerHTML;
    }

    function renderMarkdown(md) {
        // 轻量 Markdown 渲染（与问答页一致）：标题/列表/加粗/分隔线/表格（pipe table）
        // 说明：不支持任意 HTML，先 escape 再做有限替换，避免 XSS。
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

        function inlineFormat(s) {
            s = escapeHtml(s);
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            return s;
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
            return cells.every(function (c) { return /^:?-{2,}:?$/.test(c); });
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
                for (let i = 0; i < head.length; i++) html += '<th>' + inlineFormat(head[i]) + '</th>';
                html += '</tr></thead><tbody>';
                for (let r = 0; r < rows.length; r++) {
                    const row = rows[r] || [];
                    html += '<tr>';
                    for (let c = 0; c < head.length; c++) html += '<td>' + inlineFormat(row[c] == null ? '' : row[c]) + '</td>';
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            } else if (rows.length) {
                const maxCols = Math.max.apply(null, rows.map(function (r) { return (r || []).length; }));
                html += '<div class="md-table-wrap"><table class="md-table"><tbody>';
                for (let r = 0; r < rows.length; r++) {
                    const row = rows[r] || [];
                    html += '<tr>';
                    for (let c = 0; c < maxCols; c++) html += '<td>' + inlineFormat(row[c] == null ? '' : row[c]) + '</td>';
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            }
            inTable = false;
            tableHeader = null;
            tableRows = [];
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

            if (t.startsWith('#### ')) { closeTable(); closeList(); html += '<h4>' + inlineFormat(t.slice(5)) + '</h4>'; continue; }
            if (t.startsWith('### ')) { closeTable(); closeList(); html += '<h3>' + inlineFormat(t.slice(4)) + '</h3>'; continue; }
            if (t.startsWith('## ')) { closeTable(); closeList(); html += '<h2>' + inlineFormat(t.slice(3)) + '</h2>'; continue; }
            if (t.startsWith('# ')) { closeTable(); closeList(); html += '<h1>' + inlineFormat(t.slice(2)) + '</h1>'; continue; }
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
                        i = j; // skip sep row
                        continue;
                    }
                } else {
                    if (_isTableSepRow(t)) continue;
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

    function formatTime(iso) {
        if (!iso) return '-';
        var d = new Date(iso);
        var pad = function (n) { return n < 10 ? '0' + n : n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    /** 列表缩略图：同源 /api/img 附带 token，外链原样 */
    function historyListThumbSrc(rawUrl) {
        var u = (rawUrl || '').trim();
        if (!u) return '';
        if (u.indexOf('http://') === 0 || u.indexOf('https://') === 0) return u;
        var base = window.API_BASE || '';
        var path = u.charAt(0) === '/' ? u : ('/' + u);
        var token = localStorage.getItem('token');
        var q = token ? ('?token=' + encodeURIComponent(token)) : '';
        return base + path + q;
    }

    function buildImageUrlsFromAnswerBasis(answerBasisJson) {
        if (!answerBasisJson) return [];
        var data = null;
        try {
            data = typeof answerBasisJson === 'string' ? JSON.parse(answerBasisJson) : answerBasisJson;
        } catch (e) {
            return [];
        }
        if (!data || !data.vidorag || !Array.isArray(data.vidorag.page_refs)) return [];
        var refs = data.vidorag.page_refs;
        var token = localStorage.getItem('token');
        var q = token ? ('?token=' + encodeURIComponent(token)) : '';
        var dataset = data.image_dataset || 'CompetitionDataset';
        var base = window.API_BASE || '';
        return refs.map(function (r) {
            var file = r.file || '';
            var page = r.page != null ? r.page : 1;
            var url = r.url || (base + '/api/img/' + encodeURIComponent(dataset) + '/' + encodeURIComponent(file) + q);
            return {
                url: url,
                page: page,
                file: file
            };
        });
    }

   
    function buildVolcEvidenceFromAnswerBasis(answerBasisJson) {
        var empty = { pdfs: [], volcImgs: [] };
        if (!answerBasisJson) return empty;
        var data = null;
        try {
            data = typeof answerBasisJson === 'string' ? JSON.parse(answerBasisJson) : answerBasisJson;
        } catch (e) {
            return empty;
        }
        if (!data) return empty;
        var isVolc = (data.route && String(data.route).indexOf('volc_kb') >= 0) || (Array.isArray(data.references) && data.references.length);
        if (!isVolc) return empty;
        var seenPdf = {};
        var pdfs = [];
        (data.references || []).forEach(function (r) {
            var name = (r && r.source_pdf) ? String(r.source_pdf).trim() : '';
            if (name && !seenPdf[name]) {
                seenPdf[name] = true;
                pdfs.push(name);
            }
        });
        var volcImgs = [];
        var n = 0;
        (data.references || []).forEach(function (r) {
            var u = r && r.related_image ? String(r.related_image).trim() : '';
            if (u) {
                n += 1;
                volcImgs.push({
                    url: u,
                    page: n,
                    file: '',
                    volcLabel: '资料插图 ' + n
                });
            }
        });
        (data.image_urls || []).forEach(function (u, i) {
            u = String(u || '').trim();
            if (u) {
                volcImgs.push({
                    url: u,
                    page: volcImgs.length + 1,
                    file: '',
                    volcLabel: '提问附图 ' + (i + 1)
                });
            }
        });
        return { pdfs: pdfs, volcImgs: volcImgs };
    }

    function _viewerMetaText(item, state) {
        var total = _viewerList.length || 1;
        var idx = _viewerIndex + 1;
        var base;
        if (item && item.volcLabel) {
            base = item.volcLabel + '（' + idx + '/' + total + '）';
        } else {
            var p = (item && item.page) ? item.page : (_viewerIndex + 1);
            base = '第 ' + p + ' 页（' + idx + '/' + total + '）';
        }
        if (state === 'loading') return base + ' · 正在加载图片…';
        if (state === 'error') return base + ' · 图片加载失败';
        return base;
    }

    function _viewerSet(idx) {
        if (!_viewerList || _viewerList.length === 0) return;
        _viewerIndex = (idx + _viewerList.length) % _viewerList.length;
        const item = _viewerList[_viewerIndex];
        if (!item) return;

        try { viewerImgEl.onload = null; viewerImgEl.onerror = null; } catch (e) {}
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
        if (viewerDownloadEl) {
            viewerDownloadEl.href = item.url;
            viewerDownloadEl.setAttribute('download', `page_${item.page || (_viewerIndex + 1)}.jpg`);
        }
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
        try { if (viewerImgEl) viewerImgEl.removeAttribute('src'); } catch (e) {}
        _viewerList = [];
        _viewerIndex = 0;
    }

    if (viewerCloseEl) viewerCloseEl.addEventListener('click', closeImageViewer);
    if (viewerPrevEl) viewerPrevEl.addEventListener('click', function () { _viewerSet(_viewerIndex - 1); });
    if (viewerNextEl) viewerNextEl.addEventListener('click', function () { _viewerSet(_viewerIndex + 1); });
    if (viewerEl) {
        viewerEl.addEventListener('click', function (e) {
            if (e.target === viewerEl) closeImageViewer();
        });
    }
    document.addEventListener('keydown', function (e) {
        if (!viewerEl || !viewerEl.classList.contains('is-open')) return;
        if (e.key === 'Escape') closeImageViewer();
        else if (e.key === 'ArrowLeft') _viewerSet(_viewerIndex - 1);
        else if (e.key === 'ArrowRight') _viewerSet(_viewerIndex + 1);
    });

    function getFilters() {
        return {
            keyword: document.getElementById('filterKeyword').value.trim() || undefined,
            competition_id: document.getElementById('filterContest').value || undefined,
            query_type: document.getElementById('filterType').value || undefined,
        };
    }

    async function loadHistory(page) {
        currentPage = page || 0;
        var list = document.getElementById('historyList');
        list.innerHTML = '<div class="loading-hint">加载中...</div>';

        try {
            var filters = getFilters();
            var params = new URLSearchParams();
            params.set('limit', pageSize);
            params.set('offset', currentPage * pageSize);
            if (filters.keyword) params.set('keyword', filters.keyword);
            if (filters.competition_id) params.set('competition_id', filters.competition_id);
            if (filters.query_type) params.set('query_type', filters.query_type);

            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.get('/api/history?' + params.toString())).data;
            if (json.code !== 0) throw new Error(json.message);

            var data = json.data;
            totalCount = data.total;
            renderList(data.items);
            renderPagination();
        } catch (e) {
            list.innerHTML = '<div class="loading-hint">加载失败: ' + escapeHtml(e.message) + '</div>';
        }
    }

    function renderList(items) {
        var list = document.getElementById('historyList');
        if (!items || items.length === 0) {
            list.innerHTML = '<div class="loading-hint">暂无历史记录</div>';
            return;
        }
        list.innerHTML = '';
        items.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'history-card';
            card.setAttribute('data-id', item.id);

            var tags = '';
            if (item.query_type) {
                tags += '<span class="tag ' + item.query_type + '">'
                    + (item.query_type === 'visual' ? '视觉类' : '纯文类') + '</span>';
            }
            if (item.competition_id) {
                var name = item.competition_id;
                if (name.length > 15) name = name.substring(0, 15) + '...';
                tags += '<span class="tag contest">' + escapeHtml(name) + '</span>';
            }

            var thumbSrc = historyListThumbSrc(item.list_thumb_url);
            var thumbCol = '';
            if (thumbSrc) {
                thumbCol = '<div class="card-thumb-col">'
                    + '<button type="button" class="card-thumb-btn" title="查看大图" aria-label="查看附图大图">'
                    + '<img class="card-thumb-img" src="' + escapeHtml(thumbSrc) + '" alt="" loading="lazy" draggable="false">'
                    + '</button></div>';
            }

            card.innerHTML = '<div class="card-body-row' + (thumbSrc ? ' has-thumb' : '') + '">'
                + thumbCol
                + '<div class="card-main-col">'
                + '<div class="card-header">'
                + '<span class="card-question">' + escapeHtml(item.content || '') + '</span>'
                + '<span class="card-time">' + formatTime(item.created_at) + '</span>'
                + '</div>'
                + '<div class="card-answer">' + escapeHtml((item.answer || '').substring(0, 200)) + '</div>'
                + '<div class="card-tags">' + tags + '</div>'
                + '</div></div>';

            var thumbBtn = card.querySelector('.card-thumb-btn');
            if (thumbBtn && thumbSrc) {
                thumbBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    openImageViewer([{ url: thumbSrc, page: 1, file: '', volcLabel: '列表缩略图' }], 0);
                });
            }
            var thumbImgEl = card.querySelector('.card-thumb-img');
            if (thumbImgEl) {
                thumbImgEl.addEventListener('error', function () {
                    var col = card.querySelector('.card-thumb-col');
                    if (col) col.innerHTML = '';
                    var row = card.querySelector('.card-body-row');
                    if (row) {
                        row.classList.remove('has-thumb');
                    }
                });
            }

            card.addEventListener('click', function () {
                openDetail(item.id);
            });

            list.appendChild(card);
        });
    }

    function renderPagination() {
        var pag = document.getElementById('pagination');
        pag.innerHTML = '';
        var pages = Math.ceil(totalCount / pageSize);
        if (pages <= 1) return;

        var prev = document.createElement('button');
        prev.textContent = '上一页';
        prev.disabled = currentPage <= 0;
        prev.addEventListener('click', function () { loadHistory(currentPage - 1); });
        pag.appendChild(prev);

        var maxShow = 7;
        var start = Math.max(0, currentPage - 3);
        var end = Math.min(pages, start + maxShow);
        for (var i = start; i < end; i++) {
            var btn = document.createElement('button');
            btn.textContent = i + 1;
            if (i === currentPage) btn.className = 'active';
            btn.addEventListener('click', (function (p) {
                return function () { loadHistory(p); };
            })(i));
            pag.appendChild(btn);
        }

        var next = document.createElement('button');
        next.textContent = '下一页';
        next.disabled = currentPage >= pages - 1;
        next.addEventListener('click', function () { loadHistory(currentPage + 1); });
        pag.appendChild(next);
    }

    document.getElementById('searchBtn').addEventListener('click', function () {
        loadHistory(0);
    });
    document.getElementById('filterKeyword').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') loadHistory(0);
    });

    async function openDetail(id) {
        currentDetailId = id;
        try {
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.get('/api/history/' + id)).data;
            if (json.code !== 0) throw new Error(json.message);
            var d = json.data;
            var body = document.getElementById('modalBody');
            var html = '';
            html += '<div class="detail-section"><div class="detail-label">问题</div><div class="detail-value">'
                + escapeHtml(d.content || '') + '</div></div>';
            html += '<div class="detail-section"><div class="detail-label">回答</div><div class="detail-value md">'
                + renderMarkdown(d.answer || '') + '</div></div>';
            html += '<div class="detail-section"><div class="detail-label">改写查询</div><div class="detail-value">'
                + escapeHtml(d.rewritten || '-') + '</div></div>';

            var imgs = buildImageUrlsFromAnswerBasis(d.answer_basis);
            var volcEv = buildVolcEvidenceFromAnswerBasis(d.answer_basis);
            volcEv.volcImgs.forEach(function (vi) {
                imgs.push(vi);
            });

            if (imgs.length > 0) {
                html += '<div class="detail-section"><div class="detail-label">图片依据</div><div class="detail-value history-images">';
                imgs.forEach(function (it, idx) {
                    var meta = it.volcLabel ? it.volcLabel : ('第 ' + it.page + ' 页');
                    html += '<div class="history-img-item" data-img-idx="' + idx + '">'
                        + '<img src="' + escapeHtml(it.url) + '" alt="" loading="lazy">'
                        + '<div class="history-img-meta">' + escapeHtml(meta) + '</div>'
                        + '</div>';
                });
                html += '</div></div>';
            }

            if (volcEv.pdfs.length > 0) {
                html += '<div class="detail-section"><div class="detail-label">参考文档（PDF）</div><ul class="history-volc-pdf-list">';
                volcEv.pdfs.forEach(function (name) {
                    html += '<li><span class="history-volc-pdf-ico" aria-hidden="true">📄</span>'
                        + '<span class="history-volc-pdf-name">' + escapeHtml(name) + '</span></li>';
                });
                html += '</ul></div>';
            }

            html += '<div class="detail-section" style="display:flex;gap:16px;flex-wrap:wrap">'
                + '<div><div class="detail-label">查询类型</div><span class="tag '
                + (d.query_type || '') + '">' + escapeHtml(d.query_type || '-') + '</span></div>'
                + '<div><div class="detail-label">赛事</div><span>' + escapeHtml(d.competition_id || '全部') + '</span></div>'
                + '<div><div class="detail-label">Seeker 轮次</div><span>' + (d.seeker_rounds || 0) + '</span></div>'
                + '<div><div class="detail-label">时间</div><span>' + formatTime(d.created_at) + '</span></div>'
                + '</div>';

            body.innerHTML = html;
            // 绑定点击：缩略图 -> 大图预览器
            try {
                var wrap = body.querySelector('.history-images');
                if (wrap && imgs && imgs.length) {
                    wrap.querySelectorAll('.history-img-item').forEach(function (el) {
                        el.addEventListener('click', function (e) {
                            e.preventDefault();
                            e.stopPropagation();
                            var idx = parseInt(el.getAttribute('data-img-idx') || '0', 10) || 0;
                            openImageViewer(imgs, idx);
                        });
                    });
                }
            } catch (e) {}
            document.getElementById('detailModal').classList.add('active');
        } catch (e) {
            alert('加载详情失败: ' + e.message);
        }
    }

    document.getElementById('closeModal').addEventListener('click', function () {
        document.getElementById('detailModal').classList.remove('active');
    });
    document.getElementById('closeModalBtn').addEventListener('click', function () {
        document.getElementById('detailModal').classList.remove('active');
    });
    document.getElementById('detailModal').addEventListener('click', function (e) {
        if (e.target === this) this.classList.remove('active');
    });

    document.getElementById('requeueBtn').addEventListener('click', async function () {
        if (!currentDetailId) return;
        try {
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.post('/api/history/requery', { question_id: currentDetailId })).data;
            if (json.code !== 0) throw new Error(json.message);
            var d = json.data;
            var imgs = Array.isArray(d.image_urls) ? d.image_urls.filter(Boolean).slice(0, 8) : [];
            var isVolc = !!d.is_volc_kb || (d.engine_source === 'volc_kb');
            if (isVolc && (imgs.length || d.query)) {
                try {
                    sessionStorage.setItem('volc_kb_requery_v1', JSON.stringify({
                        query: d.query || '',
                        contest: d.competition_id || '',
                        image_urls: imgs,
                    }));
                } catch (e) {
                    /* ignore quota */
                }
                try {
                    sessionStorage.removeItem('volc_kb_session_v1');
                } catch (e2) {}
                window.location.href = '/volc-kb';
                return;
            }
            var params = new URLSearchParams();
            if (d.query) params.set('q', d.query);
            if (d.competition_id) params.set('contest', d.competition_id);
            var base = isVolc ? '/volc-kb' : '/graphrag';
            window.location.href = base + (params.toString() ? ('?' + params.toString()) : '');
        } catch (e) {
            alert('重查失败: ' + e.message);
        }
    });

    contestsApi().then(function (data) {
        var sel = document.getElementById('filterContest');
        (data.contests || []).forEach(function (c) {
            var opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name || c.id;
            sel.appendChild(opt);
        });
    }).catch(function () {});

    loadHistory(0);
})();
