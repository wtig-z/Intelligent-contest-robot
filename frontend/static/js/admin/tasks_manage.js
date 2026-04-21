function headers() {
    return (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders();
}

function client() {
    return window.axios.create({
        baseURL: window.API_BASE || '',
        withCredentials: true,
        timeout: 60000,
        headers: headers(),
    });
}

var isAdmin = false;

function loadStats() {
    client().get('/api/admin/tasks/stats')
        .then(function (r) { return r.data; })
        .then(function (d) {
            document.getElementById('taskStats').textContent = JSON.stringify(d.data || d, null, 2);
        });
}

function loadRunning() {
    client().get('/api/admin/tasks/running')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tb = document.getElementById('runningBody');
            tb.innerHTML = '';
            var rows = (d.data || []);
            if (!rows.length) {
                tb.innerHTML = '<tr><td colspan="7">无运行中任务</td></tr>';
                return;
            }
            rows.forEach(function (x) {
                var tr = document.createElement('tr');
                var cancelBtn = isAdmin
                    ? '<button type="button" class="linkish" data-rid="' + (x.request_id || '') + '">中断</button>'
                    : '—';
                tr.innerHTML = '<td>' + (x.request_id || '') + '</td><td>' + (x.username || x.user_id || '') + '</td><td>' + (x.phase || '') + '</td><td>' + (x.pdf_name || '') + '</td><td>' + escapeHtml((x.message_preview || '').slice(0, 80)) + '</td><td>' + (x.elapsed_sec != null ? x.elapsed_sec : '') + '</td><td class="col-admin">' + cancelBtn + '</td>';
                tb.appendChild(tr);
            });
            tb.querySelectorAll('button[data-rid]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var rid = btn.getAttribute('data-rid');
                    if (!rid || !confirm('确定中断任务 ' + rid + ' ?')) return;
                    client().post('/api/admin/tasks/cancel', { request_id: rid })
                    .then(function (r) { return r.data; }).then(function (o) {
                        alert(o.message || 'ok');
                        loadRunning();
                        loadHist();
                    }).catch(function (e) { alert(e.message); });
                });
            });
        });
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function loadHist() {
    client().get('/api/admin/tasks/history?limit=80')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tb = document.getElementById('histBody');
            tb.innerHTML = '';
            var rows = d.data || [];
            if (!rows.length) {
                tb.innerHTML = '<tr><td colspan="8">暂无</td></tr>';
                return;
            }
            rows.forEach(function (x) {
                var tr = document.createElement('tr');
                var ts = x.finished_at ? new Date(x.finished_at * 1000).toISOString() : '';
                tr.innerHTML = '<td>' + ts + '</td><td>' + (x.request_id || '') + '</td><td>' + (x.username || x.user_id || '') + '</td><td>' + (x.status || '') + '</td><td>' + (x.interrupted ? '是' : '否') + '</td><td>' + (x.duration_ms != null ? x.duration_ms : '') + '</td><td>' + (x.engine_source || '') + '</td><td>' + escapeHtml((x.message_preview || '').slice(0, 60)) + '</td>';
                tb.appendChild(tr);
            });
        });
}

document.getElementById('btnRefreshStats').addEventListener('click', function () {
    loadStats();
    loadRunning();
    loadHist();
});

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (me === SI || (me && me.__sessionInvalid)) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    isAdmin = me && me.role === 'admin';
    document.querySelectorAll('.col-admin').forEach(function (el) {
        el.style.display = isAdmin ? '' : 'none';
    });
    loadStats();
    loadRunning();
    loadHist();
    setInterval(function () { loadRunning(); loadStats(); }, 5000);
}).catch(function () {});
