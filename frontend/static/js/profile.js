(function () {
    if (!localStorage.getItem('token')) {
        window.location.href = '/login?next=/profile';
        return;
    }

    document.getElementById('logout')?.addEventListener('click', function (e) {
        e.preventDefault();
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
            try { window.CR.Auth.clearAuth(); } catch (e) {}
        } else {
            localStorage.removeItem('token');
            localStorage.removeItem('username');
            localStorage.removeItem('user_id');
            localStorage.removeItem('is_admin');
            document.cookie = 'token=; Path=/; Max-Age=0; SameSite=Lax';
        }
        window.location.href = '/login';
    });

    // Tab switching
    document.querySelectorAll('.menu-item').forEach(function (item) {
        item.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelectorAll('.menu-item').forEach(function (m) { m.classList.remove('active'); });
            document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
            item.classList.add('active');
            var tab = item.getAttribute('data-tab');
            document.getElementById('panel-' + tab).classList.add('active');
        });
    });

    var profileData = null;

    function showAlert(id, msg, type) {
        var el = document.getElementById(id);
        el.className = 'alert ' + type;
        el.textContent = msg;
        setTimeout(function () { el.className = 'alert'; }, 4000);
    }

    async function loadProfile() {
        try {
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.get('/api/profile')).data;
            if (json.code !== 0) throw new Error(json.message);
            profileData = json.data;
            renderProfile(profileData);
        } catch (e) {
            showAlert('basicAlert', '加载失败: ' + e.message, 'error');
        }
    }

    function renderProfile(d) {
        document.getElementById('avatarInitial').textContent = (d.username || 'U')[0].toUpperCase();
        document.getElementById('profileUsername').textContent = d.username;
        document.getElementById('profileRole').textContent = d.role === 'admin' ? '管理员' : '普通用户';
        document.getElementById('profileSince').textContent = '注册于 ' + (d.created_at ? d.created_at.split('T')[0] : '-');

        document.getElementById('editUsername').value = d.username;
        document.getElementById('editPhone').value = d.phone || '';
        document.getElementById('totalQuestions').value = (d.stats && d.stats.total) || 0;

        var tc0 = d.stats && d.stats.top_contests && d.stats.top_contests[0];
        var topContest = tc0 ? (tc0.name || tc0.id) : '暂无';
        document.getElementById('topContest').value = topContest;

        var prefs = d.preferences || {};
        document.getElementById('prefTopk').value = prefs.topk || 10;
        document.getElementById('topkValue').textContent = prefs.topk || 10;
        document.getElementById('prefGmm').value = prefs.gmm_sensitivity || 0.5;
        document.getElementById('gmmValue').textContent = prefs.gmm_sensitivity || 0.5;
        if (prefs.answer_format) {
            var radio = document.querySelector('input[name="answerFormat"][value="' + prefs.answer_format + '"]');
            if (radio) radio.checked = true;
        }
        document.getElementById('privacyAnonymous').checked = prefs.privacy_anonymous || false;

        if (d.role === 'admin') {
            document.getElementById('kmeansGroup').style.display = 'block';
            if (prefs.kmeans_clusters) {
                document.getElementById('prefKmeans').value = prefs.kmeans_clusters;
            }
        }

        renderStats(d.stats || {});
        loadContestOptions(prefs.default_contest);
    }

    function renderStats(s) {
        document.getElementById('statTotal').textContent = s.total || 0;
        document.getElementById('statVisualRatio').textContent = (s.visual_ratio || 0) + '%';
        document.getElementById('statAvgSeeker').textContent = s.avg_seeker_rounds || 0;

        var vc = s.visual_count || 0;
        var tc = s.text_count || 0;
        var typeSum = vc + tc;
        if (typeSum > 0) {
            document.getElementById('barVisual').style.width = ((vc / typeSum) * 100) + '%';
            document.getElementById('barText').style.width = ((tc / typeSum) * 100) + '%';
        } else {
            document.getElementById('barVisual').style.width = '0';
            document.getElementById('barText').style.width = '0';
        }
        document.getElementById('countVisual').textContent = vc;
        document.getElementById('countText').textContent = tc;

        var listEl = document.getElementById('topContestsList');
        listEl.innerHTML = '';
        (s.top_contests || []).forEach(function (c, i) {
            var div = document.createElement('div');
            div.className = 'contest-rank';
            var disp = c.name || c.id;
            div.innerHTML = '<span class="rank-num">' + (i + 1) + '</span>'
                + '<span class="rank-name">' + disp + '</span>'
                + '<span class="rank-count">' + c.count + ' 次</span>';
            listEl.appendChild(div);
        });
        if (!s.top_contests || s.top_contests.length === 0) {
            listEl.innerHTML = '<p style="font-size:13px;color:#9ca3af;">暂无数据</p>';
        }
    }

    async function loadContestOptions(selected) {
        try {
            var data = await contestsApi();
            var sel = document.getElementById('prefDefaultContest');
            (data.contests || []).forEach(function (c) {
                var opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name || c.id;
                if (c.id === selected) opt.selected = true;
                sel.appendChild(opt);
            });
        } catch (e) { /* ignore */ }
    }

    // Range sliders
    document.getElementById('prefTopk').addEventListener('input', function () {
        document.getElementById('topkValue').textContent = this.value;
    });
    document.getElementById('prefGmm').addEventListener('input', function () {
        document.getElementById('gmmValue').textContent = this.value;
    });

    // Basic form
    document.getElementById('basicForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
            var body = {
                username: document.getElementById('editUsername').value.trim(),
                phone: document.getElementById('editPhone').value.trim(),
            };
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.put('/api/profile', body)).data;
            if (json.code !== 0) throw new Error(json.message);
            showAlert('basicAlert', '保存成功', 'success');
            localStorage.setItem('username', body.username);
            loadProfile();
        } catch (e) {
            showAlert('basicAlert', '保存失败: ' + e.message, 'error');
        }
    });

    // Preferences form
    document.getElementById('prefForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
            var body = {
                default_contest: document.getElementById('prefDefaultContest').value,
                topk: parseInt(document.getElementById('prefTopk').value),
                answer_format: document.querySelector('input[name="answerFormat"]:checked').value,
                gmm_sensitivity: parseFloat(document.getElementById('prefGmm').value),
                privacy_anonymous: document.getElementById('privacyAnonymous').checked,
            };
            var kmeans = document.getElementById('prefKmeans').value;
            if (kmeans) body.kmeans_clusters = parseInt(kmeans);
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 30000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            var json = (await cli.put('/api/profile/preferences', body)).data;
            if (json.code !== 0) throw new Error(json.message);
            showAlert('prefAlert', '偏好设置已保存', 'success');
        } catch (e) {
            showAlert('prefAlert', '保存失败: ' + e.message, 'error');
        }
    });

    // Privacy toggle
    document.getElementById('privacyAnonymous').addEventListener('change', async function () {
        try {
            var cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 20000,
                headers: (window.CR && window.CR.Auth && window.CR.Auth.getAuthHeaders) ? window.CR.Auth.getAuthHeaders() : getAuthHeaders(),
            });
            await cli.put('/api/profile/preferences', { privacy_anonymous: this.checked });
        } catch (e) { /* ignore */ }
    });

    loadProfile();
})();
