// 前端工程化日志（上报后端落盘）
// - 队列聚合：定时 + 满量触发 flush
// - sendBeacon 上报（页面关闭也能发送）
// - 服务端落盘为独立文件体系（与后端格式/切割规则对齐）

(function () {
  function pad2(n) { return n < 10 ? ('0' + n) : String(n); }
  function todayStr(d) {
    d = d || new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function safeJson(v) {
    try { return JSON.stringify(v); } catch (e) { return '"[unserializable]"'; }
  }

  class FrontLogger {
    constructor(opts) {
      this.opts = opts || {};
      this.project = this.opts.project || 'contest_robot_frontend';
      this.maxLinesPerDay = this.opts.maxLinesPerDay || 5000; // 防止 localStorage 爆炸
      this.consoleOnLocalhost = this.opts.consoleOnLocalhost !== false;
      this.queue = [];
      this.maxSize = this.opts.maxSize || 10;
      this.interval = this.opts.interval || 3000;
      this.timer = null;
      this.start();
    }

    _key(dateStr, isError) {
      return `${this.project}${isError ? '_error' : ''}_${dateStr}`;
    }

    getCommon() {
      const ua = (navigator && navigator.userAgent) ? navigator.userAgent : '';
      // 这里的 user_id / is_admin 目前项目未统一落 localStorage，
      // 所以优先从 token/me 写入的信息取；拿不到就降级为未登录。
      const token = localStorage.getItem('token');
      const userId = localStorage.getItem('user_id') || 'unlogin';
      const loggedIn = !!token && userId !== 'unlogin';
      const isAdmin = loggedIn && (localStorage.getItem('is_admin') === 'true');
      // 未登录时不沿用历史残留 username，避免出现 unlogin 但 username=xxx 的误导
      const username = loggedIn ? (localStorage.getItem('username') || 'unknown') : 'unlogin';

      return {
        user_id: userId,
        is_admin: isAdmin,
        username: username,
        url: window.location.href,
        path: window.location.pathname,
        device: ua,
        time: new Date().toISOString(),
      };
    }

    _formatLine(level, message, context) {
      // 对齐后端格式：[时间] [级别] [模块名] 内容
      const common = this.getCommon();
      const moduleName = 'frontend';
      const payload = {
        ...common,
        level,
        message,
        context: context || null,
      };
      return `[${common.time.replace('T', ' ').replace('Z', '')}] [${String(level).toUpperCase()}] [${moduleName}] ${message} | payload=${safeJson(payload)}`;
    }

    _append(line, isError) {
      const ds = todayStr();
      const k = this._key(ds, isError);
      let cur = '';
      try { cur = localStorage.getItem(k) || ''; } catch (e) {}

      // 维护行数上限：超过则截断保留最后 maxLinesPerDay 行
      const next = (cur ? (cur + '\n' + line) : line);
      let out = next;
      const lines = next.split('\n');
      if (lines.length > this.maxLinesPerDay) {
        out = lines.slice(lines.length - this.maxLinesPerDay).join('\n');
      }
      try { localStorage.setItem(k, out); } catch (e) {}
    }

    log(level, message, context) {
      const line = this._formatLine(level, message || '', context || {});
      const isError = (level === 'error');
      const common = this.getCommon();
      const entry = {
        ...common,
        level: level,
        message: message || '',
        context: context || {},
      };

      if (this.consoleOnLocalhost && (location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
        const fn = (console && console[level]) ? console[level] : console.log;
        try { fn.call(console, line); } catch (e) {}
      }

      this._append(line, false);
      if (isError) this._append(line, true);

      this.queue.push(entry);
      this.flushNow();
    }

    info(m, c) { this.log('info', m, c); }
    warn(m, c) { this.log('warn', m, c); }
    error(m, c) { this.log('error', m, c); }

    readToday(isError) {
      const ds = todayStr();
      const k = this._key(ds, !!isError);
      try { return localStorage.getItem(k) || ''; } catch (e) { return ''; }
    }

    exportToday(isError) {
      const content = this.readToday(!!isError);
      const ds = todayStr();
      const name = `${this.project}${isError ? '_error' : ''}_${ds}.log`;
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        URL.revokeObjectURL(a.href);
        a.remove();
      }, 0);
    }

    flushNow() {
      if (this.queue.length >= this.maxSize) this.flush();
    }

    start() {
      if (this.timer) return;
      this.timer = setInterval(() => this.flush(), this.interval);
    }

    flush() {
      if (!this.queue || this.queue.length === 0) return;
      const logs = this.queue.slice();
      this.queue = [];

      try {
        // 某些浏览器对 sendBeacon 的字符串载荷兼容性一般；用 Blob 明确声明 JSON
        const payload = new Blob([JSON.stringify(logs)], { type: 'application/json' });
        const ok = navigator.sendBeacon('/api/log/report', payload);
        if (!ok) {
          // sendBeacon 失败则尽力上报（不阻塞）
          if (typeof window.axios !== 'undefined') {
            window.axios.post('/api/log/report', logs, { withCredentials: true, timeout: 3000 })
              .catch(function () {});
          }
        }
      } catch (e) {
        try {
          if (typeof window.axios !== 'undefined') {
            window.axios.post('/api/log/report', logs, { withCredentials: true, timeout: 3000 })
              .catch(function () {});
          }
        } catch (e2) {}
      }
    }
  }

  // 全局挂载
  window.logger = new FrontLogger();

  // 捕获未处理错误（可选但很实用）
  // 资源加载失败（script/link/img）在多数浏览器里不会带 message，需要从 e.target 取信息
  window.addEventListener('error', function (e) {
    try {
      var t = e && e.target;
      var tag = t && t.tagName ? String(t.tagName).toLowerCase() : '';
      if (tag === 'script' || tag === 'link' || tag === 'img') {
        var src = t.src || t.href || '';
        window.logger.error('resource.load.error', {
          tag: tag,
          src: src,
          id: t.id || null,
          rel: t.rel || null,
          crossOrigin: t.crossOrigin || null,
          integrity: t.integrity || null,
          online: (typeof navigator !== 'undefined' && 'onLine' in navigator) ? navigator.onLine : null
        });
        return;
      }
    } catch (err) {}
    try {
      window.logger.error('window.error', {
        message: e && e.message,
        filename: e && e.filename,
        lineno: e && e.lineno,
        colno: e && e.colno
      });
    } catch (err) {}
  }, true);
  window.addEventListener('unhandledrejection', function (e) {
    try {
      window.logger.error('unhandledrejection', { reason: (e && e.reason) ? String(e.reason) : '' });
    } catch (err) {}
  });
})();

