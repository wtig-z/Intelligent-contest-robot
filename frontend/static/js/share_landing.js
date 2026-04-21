/**
 * 分享落地页：公开读取 /api/share/:id，无需登录
 */
(function () {
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function renderMarkdown(md) {
        md = (md == null) ? '' : String(md);
        var lines = md.replace(/\r\n/g, '\n').split('\n');
        var html = '';
        var inList = false;

        function closeList() {
            if (inList) {
                html += '</ul>';
                inList = false;
            }
        }

        function inlineFormat(s) {
            s = escapeHtml(s);
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            return s;
        }

        for (var i = 0; i < lines.length; i++) {
            var raw = lines[i];
            var line = raw.trimEnd();
            var t = line.trim();
            if (!t) {
                closeList();
                continue;
            }
            if (t.startsWith('# ')) { closeList(); html += '<h1>' + inlineFormat(t.slice(2)) + '</h1>'; continue; }
            if (t.startsWith('#### ')) { closeList(); html += '<h4>' + inlineFormat(t.slice(5)) + '</h4>'; continue; }
            if (t.startsWith('### ')) { closeList(); html += '<h3>' + inlineFormat(t.slice(4)) + '</h3>'; continue; }
            if (t.startsWith('## ')) { closeList(); html += '<h2>' + inlineFormat(t.slice(3)) + '</h2>'; continue; }
            if (t === '---') { closeList(); html += '<hr>'; continue; }
            if (t.startsWith('- ')) {
                if (!inList) { html += '<ul>'; inList = true; }
                html += '<li>' + inlineFormat(t.slice(2)) + '</li>';
                continue;
            }
            closeList();
            html += '<p>' + inlineFormat(t) + '</p>';
        }
        closeList();
        return html || '<p></p>';
    }

    var path = window.location.pathname || '';
    var seg = path.replace(/^\/+|\/+$/g, '').split('/');
    var shareId = seg[seg.length - 1] || '';

    var loadingEl = document.getElementById('shareLoading');
    var errorEl = document.getElementById('shareError');
    var cardEl = document.getElementById('shareCard');
    var qEl = document.getElementById('shareQ');
    var aEl = document.getElementById('shareA');
    var figEl = document.getElementById('shareFigure');
    var imgEl = document.getElementById('sharePreviewImg');

    if (!shareId || !window.CR || !window.CR.Api) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl) {
            errorEl.style.display = 'block';
            errorEl.textContent = '无效的分享链接';
        }
        return;
    }

    window.CR.Api.getSharePublic(shareId).then(function (j) {
        var d = j.data || {};
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl) errorEl.style.display = 'none';
        if (cardEl) cardEl.style.display = 'block';

        if (qEl) {
            qEl.innerHTML = '<p>' + escapeHtml(d.question || '').replace(/\n/g, '<br>') + '</p>';
        }
        if (aEl) {
            aEl.innerHTML = renderMarkdown(d.answer || '');
        }
        if (d.preview_image && imgEl && figEl) {
            imgEl.src = d.preview_image;
            imgEl.onload = function () { figEl.style.display = 'block'; };
            imgEl.onerror = function () { figEl.style.display = 'none'; };
        }
        document.title = '分享 · 智能竞赛客服机器人';
    }).catch(function (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl) {
            errorEl.style.display = 'block';
            errorEl.textContent = e.message || '加载失败';
        }
    });
})();
