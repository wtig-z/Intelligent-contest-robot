/* 管理后台：赛事管理 */
(function () {
    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
    function normalizeUrl(u) {
        var s = String(u || '').trim();
        if (!s) return '';
        if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
        return s;
    }
    function setMsg(text, isErr) {
        var el = document.getElementById('evtAdminMsg');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = isErr ? '#e53e3e' : '#718096';
    }

    function apiClient() {
        var headers = (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders)
            ? window.CR.Auth.getAuthHeaders()
            : { 'Content-Type': 'application/json' };
        return window.axios.create({
            baseURL: window.API_BASE || '',
            withCredentials: true,
            timeout: 30000,
            headers: headers,
        });
    }

    async function loadList() {
        var tbody = document.getElementById('evtTbody');
        var count = document.getElementById('evtCount');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="hint">加载中...</td></tr>';
        try {
            var cli = apiClient();
            var j = (await cli.get('/api/admin/events/list')).data || {};
            if (j.code !== 0) throw new Error(j.message || '加载失败');
            var items = (j.data && j.data.items) ? j.data.items : [];
            if (count) count.textContent = '共 ' + items.length + ' 项';
            if (!items.length) {
                if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="hint">暂无赛事数据，请添加</td></tr>';
                return;
            }
            var html = '';
            items.forEach(function (e, idx) {
                var url = normalizeUrl(e.official_url);
                html += '<tr data-id="' + e.id + '">';
                html += '<td>' + (idx + 1) + '</td>';
                html += '<td>' + escapeHtml(e.title) + '</td>';
                html += '<td>' + escapeHtml(e.event_date) + '</td>';
                html += '<td>' + (url ? ('<a class="btn btn-text" href="' + escapeHtml(url) + '" target="_blank" rel="noopener">🔗 查看</a>') : '<span class="hint">-</span>') + '</td>';
                html += '<td><div class="table-actions">';
                html += '<button type="button" class="btn btn-text" data-act="edit">✏️ 编辑</button>';
                html += '<button type="button" class="btn btn-danger" data-act="del">🗑 删除</button>';
                html += '</div></td>';
                html += '</tr>';
            });
            if (tbody) tbody.innerHTML = html;
        } catch (e) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="hint" style="color:#e53e3e">加载失败：' + escapeHtml(e.message) + '</td></tr>';
        }
    }

    function fillForm(e) {
        document.getElementById('evtId').value = String(e.id || '');
        document.getElementById('evtTitle').value = e.title || '';
        document.getElementById('evtDate').value = (e.event_date || '').slice(0, 10);
        document.getElementById('evtUrl').value = e.official_url || '';
        document.getElementById('evtDesc').value = e.signup_desc || '';
        var btn = document.getElementById('evtSubmitBtn');
        if (btn) btn.textContent = '✔️ 保存赛事信息';
        setMsg('已载入待编辑赛事，修改后点“保存赛事信息”。', false);
        try { document.getElementById('evtForm').scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e2) {}
    }

    function clearForm() {
        document.getElementById('evtId').value = '';
        document.getElementById('evtTitle').value = '';
        document.getElementById('evtDate').value = '';
        document.getElementById('evtUrl').value = '';
        document.getElementById('evtDesc').value = '';
        try {
            var f = document.getElementById('evtPdf');
            if (f) f.value = '';
        } catch (e) {}
        setMsg('', false);
    }

    async function uploadNoticePdf(eventId) {
        var input = document.getElementById('evtPdf');
        if (!input || !input.files || !input.files.length) return;
        var file = input.files[0];
        if (!file) return;
        if (!/\.pdf$/i.test(file.name || '')) {
            setMsg('通知文件仅支持 PDF', true);
            return;
        }
        var fd = new FormData();
        fd.append('file', file);
        var token = (window.CR && window.CR.Auth && window.CR.Auth.getToken) ? window.CR.Auth.getToken() : (localStorage.getItem('token') || '');
        var headers = {};
        if (token) headers['Authorization'] = 'Bearer ' + token;
        // 不手动写 Content-Type，让浏览器自动带 boundary
        var cli = window.axios.create({
            baseURL: window.API_BASE || '',
            withCredentials: true,
            timeout: 60000,
            headers: headers,
        });
        var j = (await cli.post('/api/admin/events/' + encodeURIComponent(eventId) + '/notice_pdf', fd)).data || {};
        if (j.code !== 0) throw new Error(j.message || '上传失败');
    }

    async function submitForm(ev) {
        ev.preventDefault();
        var id = (document.getElementById('evtId').value || '').trim();
        var title = (document.getElementById('evtTitle').value || '').trim();
        var eventDate = (document.getElementById('evtDate').value || '').trim();
        var url = (document.getElementById('evtUrl').value || '').trim();
        var desc = (document.getElementById('evtDesc').value || '').trim();
        if (!title) return setMsg('赛事名称不能为空', true);
        if (!eventDate) return setMsg('赛事日期不能为空', true);
        if (!confirm('确定要保存该赛事信息吗？')) return;
        try {
            var cli = apiClient();
            var savedId = id;
            if (!id) {
                var j1 = (await cli.post('/api/admin/events', {
                    title: title,
                    event_date: eventDate,
                    official_url: url,
                    signup_desc: desc,
                })).data || {};
                if (j1.code !== 0) throw new Error(j1.message || '添加失败');
                savedId = (j1.data && j1.data.id) ? String(j1.data.id) : '';
                setMsg('已添加赛事。', false);
            } else {
                var j2 = (await cli.put('/api/admin/events/' + encodeURIComponent(id), {
                    title: title,
                    event_date: eventDate,
                    official_url: url,
                    signup_desc: desc,
                })).data || {};
                if (j2.code !== 0) throw new Error(j2.message || '更新失败');
                setMsg('已更新赛事。', false);
            }
            // 可选上传通知 PDF
            if (savedId) {
                try {
                    await uploadNoticePdf(savedId);
                    var f = document.getElementById('evtPdf');
                    if (f && f.files && f.files.length) {
                        setMsg('已保存赛事并上传通知 PDF。', false);
                    }
                } catch (upErr) {
                    setMsg('赛事已保存，但上传通知 PDF 失败：' + (upErr && upErr.message ? upErr.message : '未知错误'), true);
                }
            }
            clearForm();
            await loadList();
        } catch (e) {
            setMsg('保存失败：' + (e && e.message ? e.message : '未知错误'), true);
        }
    }

    async function deleteEvent(id) {
        if (!id) return;
        if (!confirm('确认删除该赛事？删除后前台不再展示。')) return;
        try {
            var cli = apiClient();
            var j = (await cli.delete('/api/admin/events/' + encodeURIComponent(id))).data || {};
            if (j.code !== 0) throw new Error(j.message || '删除失败');
            setMsg('已删除赛事。', false);
            await loadList();
        } catch (e) {
            setMsg('删除失败：' + (e && e.message ? e.message : '未知错误'), true);
        }
    }

    function bindTableActions() {
        var tbody = document.getElementById('evtTbody');
        if (!tbody) return;
        tbody.addEventListener('click', async function (e) {
            var btn = e.target && e.target.closest && e.target.closest('button[data-act]');
            if (!btn) return;
            var act = btn.getAttribute('data-act');
            var tr = btn.closest('tr[data-id]');
            var id = tr ? tr.getAttribute('data-id') : '';
            if (!id) return;
            if (act === 'del') return deleteEvent(id);
            if (act === 'edit') {
                // 从行内取值（简化：不含说明与官网），载入后仍可编辑说明/官网
                var title = tr.children[1] ? tr.children[1].textContent : '';
                var dt = tr.children[2] ? tr.children[2].textContent : '';
                fillForm({ id: id, title: title, event_date: dt, official_url: '', signup_desc: '' });
            }
        });
    }

    // 退出
    var logout = document.getElementById('logout');
    if (logout && window.CR && window.CR.Auth) {
        logout.addEventListener('click', function (e) {
            e.preventDefault();
            try { window.CR.Auth.clearAuth(); } catch (e2) {}
            window.location.href = '/login?mode=admin&next=/admin';
        });
    }

    var form = document.getElementById('evtForm');
    if (form) form.addEventListener('submit', submitForm);
    var clearBtn = document.getElementById('evtClearBtn');
    if (clearBtn) clearBtn.addEventListener('click', function () { clearForm(); });
    bindTableActions();
    loadList();
})();

