(function () {
    const el = document.getElementById('kbStatus');
    if (!el) return;
    (window.CR && window.CR.Api ? window.CR.Api.kbStatus() : kbStatusApi())
        .then((r) => { el.textContent = r.message || JSON.stringify(r); })
        .catch((e) => { el.textContent = '错误: ' + e.message; });
})();
