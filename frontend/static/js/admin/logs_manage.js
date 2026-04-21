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

function renderLines(lines) {
    var el = document.getElementById('logView');
    el.innerHTML = '';
    lines.forEach(function (row) {
        var text = typeof row === 'string' ? row : ((row.t || '') + ' ' + (row.m || ''));
        var div = document.createElement('div');
        div.className = 'log-line';
        if (/ERROR|OCR|失败|PDF为空|超时/i.test(text)) div.className += ' log-line-error';
        else if (/WARN/i.test(text)) div.className += ' log-line-warn';
        div.textContent = text;
        el.appendChild(div);
    });
}

document.getElementById('btnLoadBuf').addEventListener('click', function () {
    var q = document.getElementById('logQ').value.trim();
    var level = document.getElementById('logLevel').value.trim();
    var tail = document.getElementById('logTail').value || '400';
    var u = '/api/admin/logs/buffer?tail=' + encodeURIComponent(tail);
    if (q) u += '&q=' + encodeURIComponent(q);
    if (level) u += '&level=' + encodeURIComponent(level);
    document.getElementById('logView').textContent = '加载中…';
    client().get(u)
        .then(function (r) { return r.data; })
        .then(function (d) {
            var rows = d.data || [];
            if (!rows.length) {
                document.getElementById('logView').textContent = '内存缓冲为空（还没有缓存到日志，或筛选条件过严）。';
                return;
            }
            renderLines(rows.map(function (x) { return (x.t || '') + ' ' + (x.m || ''); }));
        })
        .catch(function (e) {
            var msg = (e.response && e.response.data && e.response.data.message) || e.message || '加载失败';
            document.getElementById('logView').textContent = '加载失败：' + msg;
        });
});

document.getElementById('btnLoadFile').addEventListener('click', function () {
    var dt = document.getElementById('logDate').value;
    var q = document.getElementById('fileQ').value.trim();
    var u = '/api/admin/logs/file?tail=1500';
    if (dt) u += '&date=' + encodeURIComponent(dt);
    if (q) u += '&q=' + encodeURIComponent(q);
    client().get(u)
        .then(function (r) { return r.data; })
        .then(function (d) {
            var lines = (d.data && d.data.lines) || [];
            document.getElementById('fileView').textContent = lines.join('');
        });
});

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (me === SI || (me && me.__sessionInvalid)) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    if (me && me.role === 'admin') {
        var a = document.getElementById('btnDownload');
        if (a) {
            a.style.display = '';
            a.addEventListener('click', function (ev) {
                ev.preventDefault();
                var dt = document.getElementById('logDate').value || '';
                var url = '/api/admin/logs/download' + (dt ? ('?date=' + encodeURIComponent(dt)) : '');
                window.axios.get((window.API_BASE || '') + url, { headers: headers(), withCredentials: true, responseType: 'blob', timeout: 120000 })
                    .then(function (r) { return r.data; })
                    .then(function (blob) {
                        var u = URL.createObjectURL(blob);
                        var x = document.createElement('a');
                        x.href = u;
                        x.download = 'contest_robot_' + (dt || 'today') + '.log';
                        x.click();
                        URL.revokeObjectURL(u);
                    })
                    .catch(function (e) { alert(e.message); });
            });
        }
    }
}).catch(function () {});
