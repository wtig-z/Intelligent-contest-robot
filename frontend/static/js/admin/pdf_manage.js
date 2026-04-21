function headers() {
    return (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders();
}

var boRole = 'admin';

function client() {
    return window.axios.create({
        baseURL: window.API_BASE || '',
        withCredentials: true,
        timeout: 120000,
        headers: headers(),
    });
}

function pipeLabel(p) {
    if (!p) return '-';
    var ocr = p.ocr_complete ? 'OCR已完成' : 'OCR未完成';
    var tx = p.text_extracted ? '文本已生成' : '文本未生成';
    var img = (p.image_pages != null && p.image_pages > 0) ? ('已生成图片' + p.image_pages + '页') : '图片未生成';
    return ocr + ' / ' + tx + ' / ' + img;
}

function statusLabel(s) {
    var v = (s || '').toLowerCase();
    if (v === 'processed') return '已处理';
    if (v === 'archived') return '已归档';
    if (v === 'pending') return '已登记';
    return (s || '-');
}

function escapeHtml(s) {
    if (s == null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function notify(msg, type, timeoutMs) {
    try {
        var el = document.createElement('div');
        el.className = 'notification ' + (type || 'info');
        el.textContent = String(msg || '');
        document.body.appendChild(el);
        var ms = (timeoutMs == null) ? 2600 : timeoutMs;
        setTimeout(function () {
            try { el.remove(); } catch (e) { try { document.body.removeChild(el); } catch (e2) {} }
        }, ms);
    } catch (e) {
        try { alert(msg); } catch (e2) {}
    }
}

function _extractErrMsg(e) {
    return (e && e.response && e.response.data && e.response.data.message) || (e && e.message) || '请求失败';
}

var _kbPollTimer = null;
var _kbPollingJobId = '';
var _KB_JOB_STORAGE_KEY = 'cr_admin_kb_job_id';

function _kbSetProgress(pct, label, status) {
    var wrap = document.getElementById('kbJobProgress');
    var bar = document.getElementById('kbJobProgressBar');
    var lab = document.getElementById('kbJobProgressLabel');
    if (wrap) wrap.style.display = '';
    var v = pct;
    if (v == null || isNaN(v)) v = 0;
    v = Math.max(0, Math.min(100, Math.round(v)));
    if (bar) {
        bar.style.width = v + '%';
        if (status === 'error') bar.style.background = 'linear-gradient(90deg,#ff7a45,#f53f3f)';
        else bar.style.background = 'linear-gradient(90deg,#36a3ff,#1677ff)';
    }
    if (lab) lab.textContent = (label || ('进度 ' + v + '%'));
}

function _kbHideProgress() {
    var wrap = document.getElementById('kbJobProgress');
    if (wrap) wrap.style.display = 'none';
    var bar = document.getElementById('kbJobProgressBar');
    if (bar) bar.style.width = '0%';
}

function _kbInferProgress(o) {
    // Heuristic progress from latest output lines
    var lines = (o && o.lines && o.lines.length) ? o.lines : [];
    var tail = lines.slice(-80).join('\n');
    var pct = null;
    var stage = '';

    function _m(re) { var m = tail.match(re); return m ? parseInt(m[1], 10) : null; }
    var vlm = _m(/VLM OCR:\s+(\d+)%/);
    var ing = _m(/Ingestion:\s+(\d+)%/);
    if (ing != null) { pct = 80 + ing * 0.2; stage = '嵌入中'; return { pct: pct, stage: stage }; }
    if (vlm != null) { pct = 20 + vlm * 0.4; stage = 'VLM OCR中'; return { pct: pct, stage: stage }; }
    if (tail.indexOf('[5/5]') >= 0 || tail.indexOf('嵌入') >= 0) return { pct: 82, stage: '嵌入中' };
    if (tail.indexOf('[4/5]') >= 0 || tail.indexOf('融合完成') >= 0) return { pct: 75, stage: '融合中' };
    if (tail.indexOf('[3/5]') >= 0) return { pct: 22, stage: 'VLM OCR中' };
    if (tail.indexOf('[2/5]') >= 0 || tail.indexOf('PaddleOCR') >= 0) return { pct: 12, stage: 'OCR中' };
    if (tail.indexOf('[1/5]') >= 0 || tail.indexOf('PDF → 图片') >= 0) return { pct: 6, stage: '图片生成中' };
    return { pct: 5, stage: '准备中' };
}

function startKbJobPolling(jobId, onDone) {
    var jid = String(jobId || '').trim();
    if (!jid) return;
    _kbPollingJobId = jid;
    try { sessionStorage.setItem(_KB_JOB_STORAGE_KEY, jid); } catch (e0) {}
    var pre = document.getElementById('kbJobOut');
    if (pre) {
        pre.style.display = '';
        pre.textContent = '已触发任务：' + jid + '\n等待输出…';
    }
    _kbSetProgress(3, '任务已启动，准备中…', 'running');
    if (_kbPollTimer) {
        try { clearInterval(_kbPollTimer); } catch (e) {}
        _kbPollTimer = null;
    }
    _kbPollTimer = setInterval(function () {
        client().get('/api/admin/pdf/jobs/' + encodeURIComponent(jid))
            .then(function (r) { return r.data; })
            .then(function (d) {
                if (!d || d.code !== 0) return;
                var o = d.data || {};
                var head = '[任务] ' + (o.job_id || jid)
                    + ' | 状态: ' + (o.status || '-')
                    + ' | 用时: ' + (o.elapsed_sec != null ? (o.elapsed_sec + 's') : '-');
                var lines = (o.lines && o.lines.length) ? o.lines.slice(-120).join('\n') : '（暂无输出）';
                if (pre) pre.textContent = head + '\n\n' + lines;
                var inf = _kbInferProgress(o);
                _kbSetProgress(inf.pct, inf.stage + '（' + (o.elapsed_sec != null ? (o.elapsed_sec + 's') : '-') + '）', o.status);
                if (o.status === 'success' || o.status === 'error') {
                    try { clearInterval(_kbPollTimer); } catch (e) {}
                    _kbPollTimer = null;
                    try { sessionStorage.removeItem(_KB_JOB_STORAGE_KEY); } catch (e0) {}
                    if (o.status === 'success') notify('任务已完成', 'success', 2600);
                    else notify('任务失败（请看下方输出）', 'error', 3800);
                    if (o.status === 'success') {
                        _kbSetProgress(100, '已完成', 'success');
                        setTimeout(function () { _kbHideProgress(); }, 1200);
                    } else {
                        _kbSetProgress(inf.pct || 100, '失败（请查看输出）', 'error');
                    }
                    // 完成后刷新一次列表
                    try { setTimeout(loadPdfList, 600); } catch (e2) {}
                    try { if (typeof onDone === 'function') onDone(o); } catch (e3) {}
                }
            })
            .catch(function () {
                // job 可能被重启清空，停止轮询
                try { clearInterval(_kbPollTimer); } catch (e) {}
                _kbPollTimer = null;
                try { sessionStorage.removeItem(_KB_JOB_STORAGE_KEY); } catch (e0) {}
                notify('无法获取任务进度（服务可能已重启）', 'warning', 3200);
                _kbSetProgress(100, '进度获取失败（服务可能已重启）', 'error');
                try { if (typeof onDone === 'function') onDone({ status: 'error' }); } catch (e3) {}
            });
    }, 1200);
}

function resumeKbJobPollingIfAny() {
    var jid = '';
    try { jid = String(sessionStorage.getItem(_KB_JOB_STORAGE_KEY) || '').trim(); } catch (e) { jid = ''; }
    if (!jid) return;
    // 避免重复启动
    if (_kbPollingJobId && _kbPollingJobId === jid && _kbPollTimer) return;
    notify('检测到未完成任务，已自动恢复进度显示…', 'info', 1800);
    startKbJobPolling(jid);
}

function loadPdfList() {
    client().get('/api/admin/pdf/list')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tbody = document.getElementById('pdfList');
            tbody.innerHTML = '';
            if (d.code === 0 && d.data && d.data.length) {
                d.data.forEach(function (p) {
                    var tr = document.createElement('tr');
                    var pdfLink = '<a href="/api/admin/pdf/' + p.id + '/file" target="_blank" rel="noopener">PDF</a>';
                    var txtLink = '<a href="#" class="js-text" data-id="' + p.id + '">文本</a>';
                    var rep = (boRole === 'viewer') ? '' : (' · <button type="button" class="linkish js-reparse" data-id="' + p.id + '">重新解析</button>');
                    var renameBtn = (boRole === 'viewer') ? '' : ('<button type="button" class="linkish js-rename-contest" data-id="' + p.id + '">修改名称</button>');
                    var nameCell = '<div class="contest-name-cell"><span class="contest-name-display">' + escapeHtml(p.contest_name || '') + '</span>' + (renameBtn ? ('<span class="contest-name-actions">' + renameBtn + '</span>') : '') + '</div>';
                    tr.innerHTML = ''
                        + '<td>' + p.id + '</td>'
                        + '<td>' + escapeHtml(p.filename || '') + '</td>'
                        + '<td>' + nameCell + '</td>'
                        + '<td>' + statusLabel(p.status) + '</td>'
                        + '<td>' + pipeLabel(p.pipeline) + '</td>'
                        + '<td>' + escapeHtml(p.updated_at || '-') + '</td>'
                        + '<td>' + (p.created_at || '-') + '</td>'
                        + '<td>' + pdfLink + ' · ' + txtLink + rep + '</td>';
                    tbody.appendChild(tr);
                });
                tbody.querySelectorAll('.js-text').forEach(function (a) {
                    a.addEventListener('click', function (ev) {
                        ev.preventDefault();
                        var id = a.getAttribute('data-id');
                        client().get('/api/admin/pdf/' + id + '/text_preview?max_pages=8&max_chars=8000')
                            .then(function (r) { return r.data; })
                            .then(function (o) {
                                var t = (o.data && o.data.text) || '';
                                alert(t ? t.slice(0, 3500) + (t.length > 3500 ? '\n…' : '') : '(无文本)');
                            })
                            .catch(function () { alert('加载失败'); });
                    });
                });
                tbody.querySelectorAll('.js-reparse').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var id = btn.getAttribute('data-id');
                        if (!confirm('确定触发该文档参与增量重建？')) return;
                        var old = btn.textContent;
                        btn.disabled = true;
                        btn.textContent = '处理中…';
                        notify('已触发重新解析，后台处理中…', 'info', 2200);
                        client().post('/api/admin/pdf/' + id + '/reparse', {})
                            .then(function (r) { return r.data; })
                            .then(function (o) {
                                if (o && o.code === 0) {
                                    notify(o.message || '已触发重新解析', 'success', 2800);
                                    if (o.data && o.data.job_id) {
                                        // 进度不要“瞬间消失”：按钮保持处理中直到任务结束
                                        startKbJobPolling(o.data.job_id, function () {
                                            try { btn.disabled = false; btn.textContent = old || '重新解析'; } catch (e2) {}
                                        });
                                        return;
                                    }
                                }
                                else notify((o && o.message) || '触发失败', 'error', 3200);
                            })
                            .catch(function (e) { notify(_extractErrMsg(e), 'error', 3500); })
                            .finally(function () {
                                // 若没有 job_id（未进入轮询），这里恢复按钮；有 job_id 则由轮询结束回调恢复
                                // 刷新列表，让库状态/管线状态尽快更新（即便后台还在跑）
                                try { setTimeout(loadPdfList, 600); } catch (e2) {}
                            });
                    });
                });
                tbody.querySelectorAll('.js-rename-contest').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var id = btn.getAttribute('data-id');
                        var cell = (btn.closest && btn.closest('.contest-name-cell')) || null;
                        var span = cell ? cell.querySelector('.contest-name-display') : null;
                        var cur = (span && span.textContent) ? span.textContent.trim() : '';
                        var nv = window.prompt('请输入赛事名称（用于前台展示与历史筛选，不改 PDF 文件名）', cur);
                        if (nv === null) return;
                        nv = String(nv).trim();
                        if (!nv) { alert('赛事名称不能为空'); return; }
                        client().put('/api/admin/pdf/' + id + '/contest_name', { contest_name: nv })
                            .then(function (r) { return r.data; })
                            .then(function (o) {
                                if (o.code === 0) {
                                    if (span) span.textContent = (o.data && o.data.contest_name) ? o.data.contest_name : nv;
                                    // 实时回显即可，不强制弹窗打断演示
                                    try { btn.textContent = '已保存'; setTimeout(function () { btn.textContent = '修改名称'; }, 900); } catch (e2) {}
                                } else {
                                    alert((o && o.message) || '保存失败');
                                }
                            })
                            .catch(function (e) {
                                var msg = (e.response && e.response.data && e.response.data.message) || e.message || '保存失败';
                                alert(msg);
                            });
                    });
                });
            } else {
                tbody.innerHTML = '<tr><td colspan="7">暂无数据</td></tr>';
            }
        })
        .catch(function () { document.getElementById('pdfList').innerHTML = '<tr><td colspan="7">加载失败</td></tr>'; });
}

document.getElementById('uploadBtn').addEventListener('click', function () {
    var input = document.getElementById('pdfFile');
    if (!input.files || !input.files[0]) { alert('请选择 PDF 文件'); return; }
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fd.append('dataset', 'CompetitionDataset');
    var h = {};
    var token = localStorage.getItem('token');
    if (token) h['Authorization'] = 'Bearer ' + token;
    window.axios.post((window.API_BASE || '') + '/api/admin/pdf/upload', fd, { headers: h, withCredentials: true, timeout: 120000 })
        .then(function (r) { return r.data; })
        .then(function (d) {
            if (d.code === 0) { alert('上传成功'); input.value = ''; loadPdfList(); }
            else alert(d.message || '上传失败');
        })
        .catch(function (e) { alert('上传失败: ' + e.message); });
});

document.getElementById('batchUploadBtn').addEventListener('click', function () {
    var input = document.getElementById('pdfFiles');
    if (!input.files || !input.files.length) { alert('请选择多个 PDF'); return; }
    var fd = new FormData();
    for (var i = 0; i < input.files.length; i++) {
        fd.append('files', input.files[i]);
    }
    fd.append('dataset', 'CompetitionDataset');
    var h = {};
    var token = localStorage.getItem('token');
    if (token) h['Authorization'] = 'Bearer ' + token;
    window.axios.post((window.API_BASE || '') + '/api/admin/pdf/batch_upload', fd, { headers: h, withCredentials: true, timeout: 180000 })
        .then(function (r) { return r.data; })
        .then(function (d) {
            if (d.code === 0) {
                var f = (d.data && d.data.failed) || [];
                alert('完成：成功 ' + ((d.data && d.data.uploaded) || []).length + '，失败 ' + f.length);
                input.value = '';
                loadPdfList();
            } else alert(d.message || '失败');
        })
        .catch(function (e) { alert(e.message); });
});

document.getElementById('updateKbBtn').addEventListener('click', function () {
    if (!confirm('确定要更新知识库吗？将扫描 PDF 并重建相关图片、OCR 与向量。')) return;
    var btn = document.getElementById('updateKbBtn');
    var old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '更新中…'; }
    notify('已触发更新知识库，后台处理中…', 'info', 2200);
    client().post('/api/admin/pdf/update_kb', { dataset: 'CompetitionDataset' })
        .then(function (r) { return r.data; })
        .then(function (d) {
            if (d && d.code === 0) {
                notify(d.message || '已触发更新知识库', 'success', 2800);
                if (d.data && d.data.job_id) startKbJobPolling(d.data.job_id);
            }
            else notify((d && d.message) || '触发失败', 'error', 3200);
        })
        .catch(function (e) { notify(_extractErrMsg(e), 'error', 3500); })
        .finally(function () {
            if (btn) { btn.disabled = false; btn.textContent = old || '一键更新知识库'; }
        });
});

var _rebuildBtn = document.getElementById('rebuildStructBtn');
if (_rebuildBtn) {
    _rebuildBtn.addEventListener('click', function () {
        if (!confirm('确定仅重建结构化表吗？这会根据 TSV 生成结构化知识库并同步到 competition_structs（不跑 OCR/向量）。')) return;
        var btn = _rebuildBtn;
        var old = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = '重建中…'; }
        notify('已触发结构化表重建，后台处理中…', 'info', 2200);
        client().post('/api/admin/pdf/rebuild_structs', { dataset: 'CompetitionDataset' })
            .then(function (r) { return r.data; })
            .then(function (d) {
                if (d && d.code === 0) {
                    notify(d.message || '已触发结构化表重建', 'success', 2800);
                    if (d.data && d.data.job_id) startKbJobPolling(d.data.job_id, function () {
                        try { if (btn) { btn.disabled = false; btn.textContent = old || '仅重建结构化表'; } } catch (e2) {}
                    });
                    return;
                }
                notify((d && d.message) || '触发失败', 'error', 3200);
            })
            .catch(function (e) { notify(_extractErrMsg(e), 'error', 3500); })
            .finally(function () {
                // 若进入轮询，上面的 onDone 会恢复按钮；这里做兜底
                try { setTimeout(loadPdfList, 700); } catch (e2) {}
                if (btn && !btn.disabled) return;
                // 如果轮询没启动（无 job_id），直接恢复
                // （有 job_id 的情况按钮会一直 disabled 到轮询结束）
                // eslint-disable-next-line no-empty
            });
    });
}

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (!me || me === SI || me.__sessionInvalid) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    boRole = me.role || 'viewer';
    if (boRole === 'viewer') {
        var sec = document.getElementById('uploadSection');
        if (sec) sec.style.display = 'none';
    }
    loadPdfList();
    // 页面返回时自动恢复上一次后台任务的进度条与日志
    resumeKbJobPollingIfAny();
}).catch(function () { loadPdfList(); });
