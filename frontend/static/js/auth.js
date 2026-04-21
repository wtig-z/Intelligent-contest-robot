// 全局 API_BASE，避免多脚本重复 const 声明导致 SyntaxError
window.API_BASE = window.API_BASE || '';

// 命名空间：避免全局函数重名/覆盖
window.CR = window.CR || {};
window.CR.Auth = window.CR.Auth || {};

(function (Auth) {
    Auth.getToken = function () {
        return localStorage.getItem('token');
    };

    Auth.setToken = function (token) {
        localStorage.setItem('token', token);
    };

    Auth.setTokenCookie = function (token) {
        // 让后端页面路由（如 /admin）也能读取到登录态
        // SameSite=Lax 可防止大多数 CSRF 场景的跨站自动携带
        document.cookie = `token=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
    };

    Auth.clearTokenCookie = function () {
        document.cookie = 'token=; Path=/; Max-Age=0; SameSite=Lax';
    };

    Auth.clearAuth = function () {
        localStorage.removeItem('token');
        localStorage.removeItem('username');
        localStorage.removeItem('user_id');
        localStorage.removeItem('is_admin');
        Auth.clearTokenCookie();
    };

    Auth.isLoggedIn = function () {
        return !!Auth.getToken();
    };

    Auth.getAuthHeaders = function () {
        const token = Auth.getToken();
        const h = { 'Content-Type': 'application/json' };
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    };

    /** 会话已失效（如 token 过期），与「网络抖动返回 null」区分 */
    Auth.SESSION_INVALID = Object.freeze({ __sessionInvalid: true });

    Auth.checkAuth = async function () {
        if (typeof window.axios === 'undefined') {
            // 兜底：axios 未加载时返回 null（让调用方走“未登录”逻辑）
            return null;
        }
        try {
            const cli = window.axios.create({
                baseURL: window.API_BASE || '',
                withCredentials: true,
                timeout: 15000,
                headers: Auth.getAuthHeaders(),
            });
            const res = await cli.get('/api/auth/me');
            const data = res && res.data ? res.data : null;
            return data && data.code === 0 ? data.data : null;
        } catch (e) {
            const st = e && e.response && e.response.status;
            if (st === 401) return Auth.SESSION_INVALID;
            return null;
        }
    };

    Auth.redirectToLogin = function () {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname || '/volc-kb');
    };

    // 检查是否登录：token + user_id 都存在才算已登录（避免只有 username 遗留）
    Auth.checkLogin = function () {
        const token = localStorage.getItem('token');
        const userId = localStorage.getItem('user_id');
        return !!token && !!userId;
    };

    Auth.isAdmin = function () {
        return localStorage.getItem('is_admin') === 'true';
    };

    Auth.toLogin = function () {
        const current = window.location.pathname + (window.location.search || '');
        window.location.href = '/login?next=' + encodeURIComponent(current || '/volc-kb');
    };
})(window.CR.Auth);

// 兼容层：保留旧全局入口，内部转发到命名空间（避免漏改导致报错）
window.getAuthHeaders = window.getAuthHeaders || function () { return window.CR.Auth.getAuthHeaders(); };
window.checkAuth = window.checkAuth || function () { return window.CR.Auth.checkAuth(); };
window.clearAuth = window.clearAuth || function () { return window.CR.Auth.clearAuth(); };
window.toLogin = window.toLogin || function () { return window.CR.Auth.toLogin(); };
window.checkLogin = window.checkLogin || function () { return window.CR.Auth.checkLogin(); };
window.isAdmin = window.isAdmin || function () { return window.CR.Auth.isAdmin(); };
