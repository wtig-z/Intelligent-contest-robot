/* 赛事日历中心（游客可访问） */
(function () {
    var calEl = document.getElementById('evtCalendar');
    var monthTitleEl = document.getElementById('evtMonthTitle');
    var listEl = document.getElementById('evtList');
    var countEl = document.getElementById('evtCountHint');
    var btnPrev = document.getElementById('evtPrevBtn');
    var btnNext = document.getElementById('evtNextBtn');
    var btnToday = document.getElementById('evtTodayBtn');

    var today = new Date();
    var view = new Date(today.getFullYear(), today.getMonth(), 1);
    var allEvents = [];
    var eventsByDay = {};

    function pad2(n) { return n < 10 ? ('0' + n) : String(n); }
    function ymd(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
    function ym(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1); }

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function normalizeUrl(u) {
        var s = String(u || '').trim();
        if (!s) return '';
        if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
        return s;
    }

    async function fetchEvents() {
        var cli = window.axios.create({ baseURL: window.API_BASE || '', withCredentials: true, timeout: 20000 });
        var res = await cli.get('/api/events');
        var j = res.data || {};
        if (j.code !== 0) throw new Error(j.message || '加载失败');
        allEvents = (j.data && j.data.items) ? j.data.items : [];
        eventsByDay = {};
        allEvents.forEach(function (e) {
            var k = String(e.event_date || '').slice(0, 10);
            if (!k) return;
            if (!eventsByDay[k]) eventsByDay[k] = [];
            eventsByDay[k].push(e);
        });
    }

    function renderList() {
        if (!listEl) return;
        if (!allEvents || allEvents.length === 0) {
            listEl.innerHTML = '<div style="color:#718096;font-size:13px">暂无赛事数据</div>';
            if (countEl) countEl.textContent = '';
            return;
        }
        if (countEl) countEl.textContent = '共 ' + allEvents.length + ' 项';
        var html = '';
        allEvents.forEach(function (e) {
            var url = normalizeUrl(e.official_url);
            html += '<div class="evt-item">';
            html += '<h4>' + escapeHtml(e.title || '-') + '</h4>';
            html += '<p class="meta">日期：' + escapeHtml(e.event_date || '-') + '</p>';
            if (e.signup_desc) {
                html += '<p>' + escapeHtml(e.signup_desc) + '</p>';
            }
            if (url) {
                html += '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">访问官网</a>';
            }
            html += '</div>';
        });
        listEl.innerHTML = html;
    }

    function renderCalendar() {
        if (!calEl || !monthTitleEl) return;
        monthTitleEl.textContent = view.getFullYear() + ' 年 ' + (view.getMonth() + 1) + ' 月';
        calEl.innerHTML = '';

        var first = new Date(view.getFullYear(), view.getMonth(), 1);
        var startWeekday = first.getDay(); // 0..6
        var daysInMonth = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
        var totalCells = startWeekday + daysInMonth;
        var rows = Math.ceil(totalCells / 7);
        var cells = rows * 7;

        for (var i = 0; i < cells; i++) {
            var cell = document.createElement('div');
            cell.className = 'evt-day';
            if (i < startWeekday || i >= startWeekday + daysInMonth) {
                cell.className += ' empty';
                calEl.appendChild(cell);
                continue;
            }
            var dayNum = i - startWeekday + 1;
            var d = new Date(view.getFullYear(), view.getMonth(), dayNum);
            var key = ymd(d);
            cell.textContent = String(dayNum);

            if (d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate()) {
                cell.className += ' today';
            }
            var evs = eventsByDay[key] || [];
            if (evs.length) {
                cell.className += ' has';
                var tip = document.createElement('div');
                tip.className = 'evt-tip';
                var lines = evs.slice(0, 4).map(function (x) { return '• ' + (x.title || '-'); });
                if (evs.length > 4) lines.push('… 共 ' + evs.length + ' 项');
                tip.textContent = lines.join('\n');
                cell.appendChild(tip);
                cell.addEventListener('click', function () {
                    // 点击带赛事日期：滚动到列表顶部并高亮搜索（简化：仅滚动）
                    try { document.getElementById('evtList').scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) {}
                });
            }
            calEl.appendChild(cell);
        }
    }

    function shiftMonth(delta) {
        view = new Date(view.getFullYear(), view.getMonth() + delta, 1);
        renderCalendar();
    }

    async function boot() {
        try {
            await fetchEvents();
            renderCalendar();
            renderList();
        } catch (e) {
            if (listEl) listEl.innerHTML = '<div style="color:#e53e3e;font-size:13px">加载失败：' + escapeHtml(e.message) + '</div>';
        }
    }

    if (btnPrev) btnPrev.addEventListener('click', function () { shiftMonth(-1); });
    if (btnNext) btnNext.addEventListener('click', function () { shiftMonth(1); });
    if (btnToday) btnToday.addEventListener('click', function () { view = new Date(today.getFullYear(), today.getMonth(), 1); renderCalendar(); });

    // 退出按钮：沿用全站逻辑
    var logout = document.getElementById('logout');
    if (logout && window.CR && window.CR.Auth) {
        logout.addEventListener('click', function (e) {
            e.preventDefault();
            try { window.CR.Auth.clearAuth(); } catch (e2) {}
            window.location.href = '/login';
        });
    }

    boot();
})();

