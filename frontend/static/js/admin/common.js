document.addEventListener('DOMContentLoaded', function() {
    function hasCookieToken() {
        try {
            return (document.cookie || '').split(';').some(function (c) { return c.trim().startsWith('token='); });
        } catch (e) {
            return false;
        }
    }

    var BO_ROLES = ['admin', 'viewer'];

    const token = localStorage.getItem('token');
    if (!token && !hasCookieToken()) {
        window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        return;
    }

    if (window.CR && window.CR.Auth && typeof window.CR.Auth.checkAuth === 'function') {
        var SI = window.CR.Auth.SESSION_INVALID;
        window.CR.Auth.checkAuth().then(function(me) {
            if (!me || me === SI || me.__sessionInvalid) {
                window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
                return;
            }
            if (BO_ROLES.indexOf(me.role) < 0) {
                window.location.href = '/access-denied?reason=backoffice&next=/admin';
                return;
            }
            try {
                document.body.setAttribute('data-bo-role', me.role);
            } catch (e) {}
            applyRoleNav(me.role);
        }).catch(function() {
            window.location.href = '/login?mode=admin&next=' + encodeURIComponent(window.location.pathname || '/admin');
        });
    }

    function applyRoleNav(role) {
        document.querySelectorAll('.nav-item[data-require="admin"]').forEach(function(el) {
            el.style.display = role === 'admin' ? '' : 'none';
        });
        document.querySelectorAll('.nav-item[data-require="uploader"]').forEach(function(el) {
            el.style.display = role === 'admin' ? '' : 'none';
        });
        document.querySelectorAll('[data-require="uploader"]:not(.nav-item)').forEach(function(el) {
            el.style.display = role === 'admin' ? '' : 'none';
        });
        document.querySelectorAll('a[data-require="admin"]').forEach(function(el) {
            if (el.classList && el.classList.contains('nav-item')) return;
            el.style.display = role === 'admin' ? '' : 'none';
        });
        var label = document.querySelector('.sidebar-header .role');
        if (label) {
            if (role === 'admin') label.textContent = '管理员';
            else if (role === 'viewer') label.textContent = '访客';
        }
    }

    document.querySelectorAll('#logout').forEach(function(el) {
        el.addEventListener('click', function(e) {
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
    });
});
