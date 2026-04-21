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

function loadCfg() {
    client().get('/api/admin/config')
        .then(function (r) { return r.data; })
        .then(function (d) {
            var c = d.data || {};
            document.getElementById('cfgRaw').textContent = JSON.stringify(c, null, 2);
            var form = document.getElementById('cfgForm');
            ['temperature', 'top_p', 'max_tokens', 'log_capacity', 'vector_recall_topk', 'graphrag_mode_default', 'qa_interrupt_timeout_sec'].forEach(function (k) {
                var el = form.elements.namedItem(k);
                if (el && c[k] != null) el.value = c[k];
            });
            if (form.elements.namedItem('show_images')) form.elements.namedItem('show_images').checked = !!c.show_images;
            if (form.elements.namedItem('ocr_enabled')) form.elements.namedItem('ocr_enabled').checked = !!c.ocr_enabled;
            if (form.elements.namedItem('kb_update_graphrag_input')) form.elements.namedItem('kb_update_graphrag_input').checked = !!c.kb_update_graphrag_input;
            if (form.elements.namedItem('kb_generate_vlm_box_images')) form.elements.namedItem('kb_generate_vlm_box_images').checked = !!c.kb_generate_vlm_box_images;
        });
}

document.getElementById('cfgForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var form = ev.target;
    var body = {
        temperature: parseFloat(form.temperature.value),
        top_p: parseFloat(form.top_p.value),
        max_tokens: parseInt(form.max_tokens.value, 10),
        log_capacity: parseInt(form.log_capacity.value, 10),
        vector_recall_topk: parseInt(form.vector_recall_topk.value, 10),
        graphrag_mode_default: form.graphrag_mode_default.value,
        qa_interrupt_timeout_sec: parseInt(form.qa_interrupt_timeout_sec.value, 10),
        show_images: form.show_images.checked,
        ocr_enabled: form.ocr_enabled.checked,
        kb_update_graphrag_input: !!form.kb_update_graphrag_input.checked,
        kb_generate_vlm_box_images: !!form.kb_generate_vlm_box_images.checked,
    };
    var dk = (form.dashscope_api_key.value || '').trim();
    var ok = (form.ocr_api_key.value || '').trim();
    if (dk) body.dashscope_api_key = dk;
    if (ok) body.ocr_api_key = ok;
    client().put('/api/admin/config', body)
        .then(function (r) { return r.data; })
        .then(function (o) {
            alert(o.message || 'ok');
            loadCfg();
        })
        .catch(function (e) { alert(e.message); });
});

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
    loadCfg();
}).catch(function () {});
