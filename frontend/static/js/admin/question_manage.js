function headers() {
    return (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders();
}

function client() {
    return window.axios.create({
        baseURL: window.API_BASE || '',
        withCredentials: true,
        timeout: 30000,
        headers: headers(),
    });
}

function buildQuery() {
    var q = 'limit=100&offset=0';
    var uid = document.getElementById('fUser').value.trim();
    if (uid) q += '&user_id=' + encodeURIComponent(uid);
    var c = document.getElementById('fContest').value.trim();
    if (c) q += '&competition_id=' + encodeURIComponent(c);
    var kw = document.getElementById('fKw').value.trim();
    if (kw) q += '&keyword=' + encodeURIComponent(kw);
    var df = document.getElementById('fFrom').value;
    var dt = document.getElementById('fTo').value;
    if (df) q += '&date_from=' + encodeURIComponent(df);
    if (dt) q += '&date_to=' + encodeURIComponent(dt);
    return q;
}

function loadQuestions() {
    client().get('/api/admin/questions/list?' + buildQuery())
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tbody = document.getElementById('questionList');
            tbody.innerHTML = '';
            if (d.code === 0 && d.data) {
                document.getElementById('totalCount').textContent = d.data.total || 0;
                var items = d.data.items || [];
                if (items.length) {
                    items.forEach(function (q) {
                        var tr = document.createElement('tr');
                        var basis = (q.answer_basis || '').slice(0, 120);
                        tr.innerHTML = ''
                            + '<td>' + q.id + '</td>'
                            + '<td>' + (q.username || q.user_id || '-') + '</td>'
                            + '<td>' + (q.content || '').substring(0, 100) + '</td>'
                            + '<td>' + ((q.answer || '').substring(0, 100)) + '</td>'
                            + '<td>' + (q.engine_source || '-') + '</td>'
                            + '<td>' + (q.competition_id || '-') + '</td>'
                            + '<td title="' + basis.replace(/"/g, '&quot;') + '">' + basis + '</td>'
                            + '<td>' + (q.created_at || '-') + '</td>';
                        tbody.appendChild(tr);
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="8">暂无数据</td></tr>';
                }
            } else {
                tbody.innerHTML = '<tr><td colspan="8">加载失败</td></tr>';
            }
        })
        .catch(function () { document.getElementById('questionList').innerHTML = '<tr><td colspan="8">加载失败</td></tr>'; });
}

document.getElementById('btnSearch').addEventListener('click', loadQuestions);

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (me === SI || (me && me.__sessionInvalid)) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    loadQuestions();
}).catch(function () { loadQuestions(); });
