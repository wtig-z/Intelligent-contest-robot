function headers() {
    return (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders();
}

function downloadBlob(blob, name) {
    var u = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = u;
    a.download = name;
    a.click();
    URL.revokeObjectURL(u);
}

document.getElementById('btnCsv').addEventListener('click', function () {
    window.axios.get((window.API_BASE || '') + '/api/admin/export/conversations.csv?limit=8000', {
        headers: headers(),
        withCredentials: true,
        responseType: 'blob',
        timeout: 120000
    })
        .then(function (r) { return r.data; })
        .then(function (b) { downloadBlob(b, 'conversations.csv'); })
        .catch(function (e) { alert(e.message); });
});

document.getElementById('btnGraph').addEventListener('click', function () {
    var url = '/api/admin/export/graphrag_entities_relationships.json';
    window.axios.get((window.API_BASE || '') + url, {
        headers: headers(),
        withCredentials: true,
        responseType: 'blob',
        timeout: 120000,
        validateStatus: function (s) { return (s >= 200 && s < 300) || s === 400 || s === 403 || s === 404 || s === 500; }
    })
        .then(function (r) {
            // 失败时后端会返回 json；axios 在 responseType=blob 时也会是 blob，需要尝试读文本
            if (r.status >= 200 && r.status < 300) return r.data;
            return r.data.text().then(function (t) { throw new Error((JSON.parse(t).message) || '导出失败'); });
        })
        .then(function (b) { downloadBlob(b, 'graphrag_entities_relationships.json'); })
        .catch(function (e) { alert(e.message); });
});

document.getElementById('btnManifest').addEventListener('click', function () {
    window.axios.get((window.API_BASE || '') + '/api/admin/export/documents_manifest.json', {
        headers: headers(),
        withCredentials: true,
        responseType: 'blob',
        timeout: 120000
    })
        .then(function (r) { return r.data; })
        .then(function (b) { downloadBlob(b, 'documents_manifest.json'); })
        .catch(function (e) { alert(e.message); });
});

document.getElementById('btnReport').addEventListener('click', function () {
    window.axios.create({ baseURL: window.API_BASE || '', withCredentials: true, timeout: 30000, headers: headers() })
        .get('/api/admin/export/report.json')
        .then(function (r) { return r.data; })
        .then(function (d) {
            document.getElementById('reportOut').textContent = JSON.stringify(d.data || d, null, 2);
        })
        .catch(function () { document.getElementById('reportOut').textContent = '加载失败'; });
});

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (!me || me === SI || me.__sessionInvalid) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    if (me.role !== 'admin') {
        window.location.href = '/access-denied?reason=admin&next=/admin';
    }
}).catch(function () {});
