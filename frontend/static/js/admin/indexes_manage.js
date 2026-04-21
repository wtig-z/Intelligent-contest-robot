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

function loadCfg() {
    client().get('/api/admin/config')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var c = d.data || {};
            var pre = document.getElementById('idxCfgRaw');
            if (pre) pre.textContent = JSON.stringify({
                graphrag_mode_default: c.graphrag_mode_default,
                log_capacity: c.log_capacity,
                max_tokens: c.max_tokens,
                ocr_enabled: !!c.ocr_enabled,
                qa_interrupt_timeout_sec: c.qa_interrupt_timeout_sec,
                show_images: !!c.show_images,
                temperature: c.temperature,
                top_p: c.top_p,
                vector_recall_topk: c.vector_recall_topk,
            }, null, 2);
            var form = document.getElementById('idxCfgForm');
            if (form) {
                ['temperature', 'top_p', 'max_tokens', 'log_capacity', 'vector_recall_topk', 'graphrag_mode_default', 'qa_interrupt_timeout_sec', 'dashscope_api_key', 'ocr_api_key'].forEach(function (k) {
                    var el = form.elements.namedItem(k);
                    if (el && c[k] != null) el.value = c[k];
                });
                if (form.elements.namedItem('show_images')) form.elements.namedItem('show_images').checked = !!c.show_images;
                if (form.elements.namedItem('ocr_enabled')) form.elements.namedItem('ocr_enabled').checked = !!c.ocr_enabled;
            }
        })
        .catch(function () {
            var pre = document.getElementById('idxCfgRaw');
            if (pre) pre.textContent = '加载失败';
        });
}

function loadSummary() {
    client().get('/api/admin/indexes/summary')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var data = d.data || {};
            var pretty = document.getElementById('idxSummaryPretty');
            if (pretty) {
                var g = data.graphrag || {};
                var v = data.vidorag_vectors || {};
                var docsMissing = (data.documents_missing_text || []).length;
                var anCount = (data.anomalies || []).length;
                var rows = [
                    ['dataset', '<code>' + (data.dataset || '-') + '</code>'],
                    ['pdf_count（已登记PDF数）', String(data.pdf_count != null ? data.pdf_count : '-')],
                    ['vector_rows_in_db（DB向量行数）', String(data.vector_rows_in_db != null ? data.vector_rows_in_db : '-')],
                    ['vidorag_vectors（.node文件数）', String(v.bge_node_files != null ? v.bge_node_files : '-')],
                    ['vidorag_vectors（最近更新时间）', String(v.bge_dir_mtime || '-')],
                    ['graphrag.available', String(g.available != null ? g.available : '-')],
                    ['graphrag.output_dir_ready', String(g.output_dir_ready != null ? g.output_dir_ready : '-')],
                    ['graphrag.text_units', String(g.text_units != null ? g.text_units : '-')],
                    ['graphrag.entities', String(g.entities != null ? g.entities : '-')],
                    ['graphrag.relationships', String(g.relationships != null ? g.relationships : '-')],
                    ['graphrag.communities', String(g.communities != null ? g.communities : '-')],
                    ['graphrag.community_reports', String(g.community_reports != null ? g.community_reports : '-')],
                    ['documents_missing_text（未生成统一文本）', String(docsMissing)],
                    ['anomalies（异常条数）', String(anCount)],
                ];
                pretty.innerHTML = rows.map(function (kv) {
                    return '<div class="k">' + kv[0] + '</div><div class="v">' + kv[1] + '</div>';
                }).join('');
            }
            document.getElementById('idxSummary').textContent = JSON.stringify(data, null, 2);
            var an = [];
            if (data.anomalies && data.anomalies.length) an.push('anomalies: ' + JSON.stringify(data.anomalies, null, 2));
            if (data.documents_missing_text && data.documents_missing_text.length) {
                an.push('missing unified_text: ' + data.documents_missing_text.join(', '));
            }
            document.getElementById('idxAnomalies').textContent = an.length ? an.join('\n\n') : '暂无';
        })
        .catch(function () {
            document.getElementById('idxSummary').textContent = '加载失败';
        });
}

document.getElementById('btnRefresh').addEventListener('click', loadSummary);

document.getElementById('btnRebuildVec').addEventListener('click', function () {
    if (!confirm('确定触发向量与 OCR 管线重建？')) return;
    client().post('/api/admin/indexes/rebuild_vectors', {})
        .then(function (r) { return r.data; })
        .then(function (d) { alert(d.message || (d.code === 0 ? '已触发' : '失败')); })
        .catch(function (e) { alert(e.message); });
});

document.getElementById('btnRebuildGraph').addEventListener('click', function () {
    if (!confirm('确定启动 GraphRAG 全量构建？可能耗时较长。')) return;
    client().post('/api/admin/indexes/rebuild_graph', {})
        .then(function (r) { return r.data; })
        .then(function (d) { alert(d.message || (d.code === 0 ? '已启动' : '失败')); })
        .catch(function (e) { alert(e.message); });
});

window.CR.Auth.checkAuth().then(function (me) {
    var SI = window.CR.Auth.SESSION_INVALID;
    if (!me || me === SI || me.__sessionInvalid) return;
    var role = me && me.role;
    if (role === 'admin') {
        var b = document.getElementById('btnRebuildVec');
        if (b) b.style.display = '';
    }
    if (role === 'admin') {
        var g = document.getElementById('btnRebuildGraph');
        if (g) g.style.display = '';
    }
}).catch(function () {});

loadCfg();
loadSummary();
