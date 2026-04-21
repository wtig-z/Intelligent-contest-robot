window.axios.create({
    baseURL: window.API_BASE || '',
    withCredentials: true,
    timeout: 30000,
    headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders()
}).get('/api/admin/vectors/list')
    .then(function (res) { return res.data; })
    .then(function (d) {
        var tbody = document.getElementById('vectorList');
        tbody.innerHTML = '';
        if (d.code === 0 && d.data && d.data.length) {
            d.data.forEach(function (v) {
                var tr = document.createElement('tr');
                var st = (v.status || '').toLowerCase();
                var cls = 'vec-status-pending';
                if (st.indexOf('building') >= 0) cls = 'vec-status-building';
                else if (st.indexOf('completed') >= 0) cls = 'vec-status-completed';
                else if (st.indexOf('failed') >= 0) cls = 'vec-status-failed';
                else if (st.indexOf('pending') >= 0) cls = 'vec-status-pending';
                var prog = typeof v.progress === 'number' ? v.progress : parseInt(v.progress, 10) || 0;
                var bar = '<div class="vec-progress-wrap"><div class="vec-progress-bar" style="width:' + Math.min(100, prog) + '%"></div></div>';
                tr.innerHTML =
                    '<td>' + (v.id != null ? v.id : '-') + '</td>' +
                    '<td>' + (v.dataset || '-') + '</td>' +
                    '<td>' + (v.vector_type || '-') + '</td>' +
                    '<td><span class="vec-status ' + cls + '">' + (v.status || '-') + '</span></td>' +
                    '<td>' + bar + ' <small>' + prog + '%</small></td>' +
                    '<td style="font-size:12px;max-width:200px;word-break:break-all">' + (v.file_path || '-') + '</td>' +
                    '<td class="vec-err">' + (v.error_msg || '') + '</td>' +
                    '<td style="font-size:12px">' + (v.updated_at || v.created_at || '') + '</td>';
                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = '<tr><td colspan="8">暂无数据</td></tr>';
        }
    })
    .catch(function () {
        document.getElementById('vectorList').innerHTML = '<tr><td colspan="8">加载失败</td></tr>';
    });
