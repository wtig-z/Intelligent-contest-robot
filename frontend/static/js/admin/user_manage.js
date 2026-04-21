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

function loadUsers() {
    client().get('/api/admin/users/list')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tbody = document.getElementById('userList');
            tbody.innerHTML = '';
            if (d.code === 0 && d.data && d.data.length) {
                d.data.forEach(function (u) {
                    var tr = document.createElement('tr');
                    var sel = ''
                        + '<select class="role-sel" data-id="' + u.id + '">'
                        + '<option value="user"' + (u.role === 'user' ? ' selected' : '') + '>user</option>'
                        + '<option value="admin"' + (u.role === 'admin' ? ' selected' : '') + '>admin</option>'
                        + '<option value="viewer"' + (u.role === 'viewer' ? ' selected' : '') + '>viewer</option>'
                        + '</select>';
                    tr.innerHTML = ''
                        + '<td>' + u.id + '</td>'
                        + '<td>' + (u.username || '') + '</td>'
                        + '<td>' + (u.phone || '') + '</td>'
                        + '<td>' + (u.role || 'user') + '</td>'
                        + '<td>' + sel + ' <button type="button" class="btn-primary btn-save-role" data-id="' + u.id + '">保存</button></td>';
                    tbody.appendChild(tr);
                });
                tbody.querySelectorAll('.btn-save-role').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var id = parseInt(btn.getAttribute('data-id'), 10);
                        var row = btn.closest('tr');
                        var sel = row && row.querySelector('.role-sel');
                        var role = sel ? sel.value : '';
                        if (!id || !role) return;
                        client().post('/api/admin/users/role', { user_id: id, role: role })
                            .then(function (r) { return r.data; })
                            .then(function (o) {
                                alert(o.message || 'ok');
                                loadUsers();
                            })
                            .catch(function () { alert('失败'); });
                    });
                });
            } else {
                tbody.innerHTML = '<tr><td colspan="5">暂无数据</td></tr>';
            }
        })
        .catch(function () { document.getElementById('userList').innerHTML = '<tr><td colspan="5">加载失败</td></tr>'; });
}

function loadResetRequests() {
    client().get('/api/admin/users/reset-requests/list')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var tbody = document.getElementById('resetRequestList');
            tbody.innerHTML = '';
            if (d.code === 0 && d.data && d.data.length) {
                d.data.forEach(function (r) {
                    var tr = document.createElement('tr');
                    var time = r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '-';
                    tr.innerHTML =
                        '<td>' + r.id + '</td>' +
                        '<td>' + (r.phone || '') + '</td>' +
                        '<td>' + (r.username != null ? r.username : '未注册') + '</td>' +
                        '<td>' + time + '</td>' +
                        '<td><button type="button" class="btn-approve" data-id="' + r.id + '">重置并发短信</button></td>';
                    tbody.appendChild(tr);
                });
                tbody.querySelectorAll('.btn-approve').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var id = parseInt(btn.getAttribute('data-id'), 10);
                        if (!id) return;
                        btn.disabled = true;
                        btn.textContent = '处理中…';
                        client().post('/api/admin/users/reset-requests/' + id + '/approve', {})
                            .then(function (res) { return res.data; })
                            .then(function (data) {
                                if (data.code === 0) loadResetRequests();
                                else {
                                    alert(data.message || '操作失败');
                                    btn.disabled = false;
                                    btn.textContent = '重置并发短信';
                                }
                            })
                            .catch(function () {
                                alert('请求失败');
                                btn.disabled = false;
                                btn.textContent = '重置并发短信';
                            });
                    });
                });
            } else {
                tbody.innerHTML = '<tr><td colspan="5">暂无待处理申请</td></tr>';
            }
        })
        .catch(function () { document.getElementById('resetRequestList').innerHTML = '<tr><td colspan="5">加载失败</td></tr>'; });
}

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (!me || me === SI || me.__sessionInvalid) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }
    if (me.role !== 'admin') {
        window.location.href = '/access-denied?reason=admin&next=/admin';
        return;
    }
    loadUsers();
    loadResetRequests();
}).catch(function () {});
