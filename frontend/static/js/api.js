// 全局 API_BASE，避免多脚本重复 const 声明导致 SyntaxError
window.API_BASE = window.API_BASE || '';

window.CR = window.CR || {};
window.CR.Api = window.CR.Api || {};

(function (Api) {
    function _ensureAxios() {
        if (typeof window.axios === 'undefined') {
            throw new Error('axios 未加载：请检查页面是否引入 axios.min.js');
        }
        return window.axios;
    }

    function _authHeaders() {
        if (window.CR && window.CR.Auth && typeof window.CR.Auth.getAuthHeaders === 'function') {
            return window.CR.Auth.getAuthHeaders();
        }
        // 兜底（极端情况下 auth.js 未加载）
        const token = localStorage.getItem('token');
        const h = { 'Content-Type': 'application/json' };
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    }

    function _client() {
        const axios = _ensureAxios();
        // 说明：使用工厂函数避免外部脚本修改 defaults 影响行为
        return axios.create({
            baseURL: window.API_BASE || '',
            withCredentials: true,
            timeout: 120000,
            headers: _authHeaders(),
        });
    }

    async function _getJson(url, config) {
        const cli = _client();
        const res = await cli.get(url, config || {});
        return res.data;
    }

    async function _postJson(url, body, config) {
        const cli = _client();
        const res = await cli.post(url, body, config || {});
        return res.data;
    }

    Api.contests = async function () {
        try {
            return await _getJson('/api/contests');
        } catch (e) {
            try {
                if (window.logger && typeof window.logger.error === 'function') {
                    window.logger.error('Api.contests failed', {
                        message: e && e.message,
                        status: e && e.response && e.response.status,
                        data: e && e.response && e.response.data
                    });
                }
            } catch (e2) {}
            throw new Error('获取赛事列表失败');
        }
    };

    Api.contestsHot = async function (days, limit) {
        const q = new URLSearchParams();
        if (days != null && days !== '') q.set('days', String(days));
        if (limit != null && limit !== '') q.set('limit', String(limit));
        const qs = q.toString();
        const url = `/api/contests/hot${qs ? '?' + qs : ''}`;
        try {
            return await _getJson(url);
        } catch (e) {
            try {
                if (window.logger && typeof window.logger.error === 'function') {
                    window.logger.error('Api.contestsHot failed', {
                        message: e && e.message,
                        status: e && e.response && e.response.status,
                        data: e && e.response && e.response.data,
                        url: url
                    });
                }
            } catch (e2) {}
            throw new Error('获取热门赛事失败');
        }
    };

    /** 中止当前进行中的问答（不发送新问题），需传上一轮 request_id */
    Api.chatCancel = async function (requestId) {
        const body = {};
        if (requestId) body.request_id = requestId;
        try {
            return await _postJson('/api/chat/cancel', body, {});
        } catch (e) {
            const status = e && e.response && e.response.status;
            if (status === 401 || status === 403) {
                throw e;
            }
            return { code: (e && e.response && e.response.data && e.response.data.code) || -1, message: 'cancel failed' };
        }
    };

    Api.chat = async function (message, history, requestId, contest, options) {
        const body = { message };
        if (Array.isArray(history) && history.length > 0) body.history = history;
        if (requestId) body.request_id = requestId;
        const cids = options && options.contest_ids;
        if (Array.isArray(cids) && cids.length > 0) {
            body.contest_ids = cids;
        } else if (contest) {
            body.pdf_name = contest;
        }
        if (options && options.cancelRequestId) body.cancel_request_id = options.cancelRequestId;
        if (options && options.deep_think != null) body.deep_think = !!options.deep_think;
        try {
            // axios v1 支持 AbortController.signal
            // 注意：服务端可能存在 QA 并发队列等待（默认最多 120s）+ LLM 推理耗时，
            // 因此这里给 /api/chat 单独放宽超时，避免前端先超时但后端仍在计算。
            return await _postJson('/api/chat', body, {
                signal: options && options.signal,
                timeout: 300000, // 5min
            });
        } catch (e) {
            const status = e && e.response && e.response.status;
            if (status === 401) {
                // 未登录：先写入提示，再跳转到登录页（带 next 回跳）
                if (window.CR && window.CR.Auth && typeof window.CR.Auth.clearAuth === 'function') {
                    try { window.CR.Auth.clearAuth(); } catch (e2) {}
                } else if (typeof clearAuth === 'function') {
                    try { clearAuth(); } catch (e2) {}
                } else {
                    try { localStorage.removeItem('token'); localStorage.removeItem('username'); localStorage.removeItem('user_id'); localStorage.removeItem('is_admin'); } catch (e2) {}
                }
                if (window.logger && typeof window.logger.warn === 'function') {
                    window.logger.warn('chatApi 收到 401，准备跳转登录页', {
                        hasLocalToken: !!localStorage.getItem('token'),
                        hasCookieToken: (document.cookie || '').indexOf('token=') >= 0,
                        next: window.location.pathname + window.location.search
                    });
                }
                try { sessionStorage.setItem('flash_login_tip', '请先登录！'); } catch (e2) {}
                const next = encodeURIComponent(window.location.pathname + window.location.search);
                window.location.href = '/login?next=' + next;
                throw new Error('请先登录再使用');
            }
            const msg = (e && e.response && e.response.data && (e.response.data.message || e.response.data.error))
                ? (e.response.data.message || e.response.data.error)
                : (e && e.message ? e.message : '请求失败');
            throw new Error(msg);
        }
    };

    Api.health = async function () {
        return await _getJson('/api/health', { withCredentials: false });
    };

    Api.kbStatus = async function () {
        return await _getJson('/api/kb/status');
    };

    Api.profile = async function () {
        try {
            return await _getJson('/api/profile');
        } catch (e) {
            throw new Error('获取个人资料失败');
        }
    };

    Api.history = async function (params) {
        const qs = new URLSearchParams(params || {}).toString();
        try {
            return await _getJson(`/api/history?${qs}`);
        } catch (e) {
            throw new Error('获取历史记录失败');
        }
    };

    /** 登录后生成分享链接（绑定 question_id） */
    Api.createShare = async function (questionId) {
        try {
            const j = await _postJson('/api/share', { question_id: questionId });
            if (!j || j.code !== 0) throw new Error((j && j.message) || '生成分享链接失败');
            return j;
        } catch (e) {
            const status = e && e.response && e.response.status;
            const j = e && e.response && e.response.data;
            if (status === 401) {
                try { sessionStorage.setItem('flash_login_tip', '请先登录后再分享'); } catch (e2) {}
                window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
                throw new Error('请先登录');
            }
            throw new Error((j && j.message) || e.message || '生成分享链接失败');
        }
    };

    /** 公开：落地页拉取问答内容，无需登录 */
    Api.getSharePublic = async function (shareId) {
        const id = encodeURIComponent(shareId);
        try {
            const j = await _getJson(`/api/share/${id}`, { withCredentials: false });
            if (!j || j.code !== 0) throw new Error((j && j.message) || '无法加载分享内容');
            return j;
        } catch (e) {
            const j = e && e.response && e.response.data;
            throw new Error((j && j.message) || e.message || '无法加载分享内容');
        }
    };
})(window.CR.Api);

// 兼容层：保留旧全局函数名，转发到命名空间（避免漏改导致报错）
window.contestsApi = window.contestsApi || function () { return window.CR.Api.contests(); };
window.contestsHotApi = window.contestsHotApi || function (days, limit) { return window.CR.Api.contestsHot(days, limit); };
window.chatApi = window.chatApi || function (message, history, requestId, contest, options) { return window.CR.Api.chat(message, history, requestId, contest, options); };
window.healthApi = window.healthApi || function () { return window.CR.Api.health(); };
window.kbStatusApi = window.kbStatusApi || function () { return window.CR.Api.kbStatus(); };
window.profileApi = window.profileApi || function () { return window.CR.Api.profile(); };
window.historyApi = window.historyApi || function (params) { return window.CR.Api.history(params); };
window.createShareApi = window.createShareApi || function (qid) { return window.CR.Api.createShare(qid); };
window.getSharePublicApi = window.getSharePublicApi || function (sid) { return window.CR.Api.getSharePublic(sid); };
