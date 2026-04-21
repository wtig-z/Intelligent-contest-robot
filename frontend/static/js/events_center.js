// 赛事信息中心：从 /api/events 拉取数据，提供搜索 + 日历标注 + 分页
(function () {
    const PAGE_SIZE = 6;

    const searchInput = document.getElementById("searchInput");
    const currentMonthEl = document.getElementById("currentMonth");
    const calendarDaysEl = document.getElementById("calendarDays");
    const yearSel = document.getElementById("calYearSelect");
    const monthSel = document.getElementById("calMonthSelect");
    const prevMonthBtn = document.getElementById("calPrevBtn");
    const nextMonthBtn = document.getElementById("calNextBtn");
    const eventListEl = document.getElementById("eventList");
    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const pageInfo = document.getElementById("pageInfo");

    const today = new Date();
    const currentDate = today.getDate();
    let viewYear = today.getFullYear();
    let viewMonth = today.getMonth(); // 0-11

    let allEventData = [];
    let filteredEvents = [];
    let currentPage = 1;
    let calendarPopupDocBound = false;

    function escapeHtml(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function normalizeUrl(u) {
        let s = String(u || "").trim();
        if (!s) return "";
        if (!/^https?:\/\//i.test(s)) s = "https://" + s;
        return s;
    }

    function formatMonth(year, month) {
        return `${year}年${month + 1}月`;
    }

    function formatDateCN(iso) {
        const d = new Date(String(iso || "").slice(0, 10));
        if (isNaN(d.getTime())) return String(iso || "");
        return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
    }

    async function fetchEvents() {
        const cli = window.axios.create({
            baseURL: window.API_BASE || "",
            withCredentials: true,
            timeout: 20000,
        });
        const res = await cli.get("/api/events");
        const j = res.data || {};
        if (j.code !== 0) throw new Error(j.message || "获取赛事数据失败");
        const items = (j.data && j.data.items) ? j.data.items : [];
        allEventData = items.map((e) => ({
            id: e.id,
            title: e.title || "",
            date: String(e.event_date || "").slice(0, 10),
            desc: e.signup_desc || "",
            url: e.official_url || "",
            pdfUrl: e.notice_pdf_url || "",
        }));
        filteredEvents = allEventData.slice();
    }

    function updatePagination() {
        const totalPages = Math.ceil(filteredEvents.length / PAGE_SIZE) || 1;
        if (pageInfo) pageInfo.innerText = `第 ${currentPage} 页 / 共 ${totalPages} 页`;
        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
    }

    function renderEventList() {
        if (!eventListEl) return;
        eventListEl.innerHTML = "";

        if (!filteredEvents.length) {
            eventListEl.innerHTML = `<div class="empty-tip">暂无匹配的赛事信息，敬请期待！</div>`;
            updatePagination();
            return;
        }

        const totalPages = Math.ceil(filteredEvents.length / PAGE_SIZE) || 1;
        if (currentPage > totalPages) currentPage = totalPages;

        const startIndex = (currentPage - 1) * PAGE_SIZE;
        const currentPageEvents = filteredEvents.slice(startIndex, startIndex + PAGE_SIZE);

        currentPageEvents.forEach((event) => {
            const url = normalizeUrl(event.url);
            const pdfUrl = String(event.pdfUrl || "").trim();
            eventListEl.innerHTML += `
                <div class="event-card">
                    <h3>${escapeHtml(event.title)}</h3>
                    <div class="info-item">举办时间：${escapeHtml(formatDateCN(event.date))}</div>
                    <div class="info-item">报名说明：${escapeHtml(event.desc || "暂无")}</div>
                    ${pdfUrl ? `<a href="${escapeHtml(pdfUrl)}" class="official-link" style="margin-right:10px;background:linear-gradient(90deg,#667eea,#764ba2)" download>下载通知PDF</a>` : ""}
                    ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="official-link">访问赛事官网</a>` : ""}
                </div>
            `;
        });

        updatePagination();
    }

    function _ensureCalendarSelectors() {
        if (!yearSel || !monthSel) return;
        if (yearSel.options && yearSel.options.length) return;
        const y0 = today.getFullYear();
        const minY = y0 - 1;
        const maxY = y0 + 5;
        for (let y = minY; y <= maxY; y++) {
            const opt = document.createElement("option");
            opt.value = String(y);
            opt.textContent = String(y) + "年";
            yearSel.appendChild(opt);
        }
        for (let m = 1; m <= 12; m++) {
            const opt2 = document.createElement("option");
            opt2.value = String(m);
            opt2.textContent = String(m) + "月";
            monthSel.appendChild(opt2);
        }
    }

    function setViewMonth(y, m0) {
        viewYear = y;
        viewMonth = m0;
        if (yearSel) yearSel.value = String(viewYear);
        if (monthSel) monthSel.value = String(viewMonth + 1);
        if (currentMonthEl) currentMonthEl.innerText = formatMonth(viewYear, viewMonth);
        renderCalendar();
    }

    function shiftMonth(delta) {
        const d = new Date(viewYear, viewMonth + delta, 1);
        setViewMonth(d.getFullYear(), d.getMonth());
    }

    function _isPopupLeft(colIndex0) {
        // 周五/周六列默认弹左侧，避免越界
        return colIndex0 >= 5;
    }

    /** 日历日期弹层：点击切换（移动端可用）；点击空白处关闭 */
    function initCalendarPopupInteractions() {
        if (!calendarDaysEl) return;
        if (!calendarDaysEl.dataset.popupDelegBound) {
            calendarDaysEl.dataset.popupDelegBound = "1";
            calendarDaysEl.addEventListener("click", function (e) {
                const cell = e.target.closest(".calendar-cell.has-event");
                if (!cell) return;
                if (e.target.closest(".event-popup")) {
                    e.stopPropagation();
                    return;
                }
                e.stopPropagation();
                const wasOpen = cell.classList.contains("popup-open");
                calendarDaysEl.querySelectorAll(".calendar-cell.has-event.popup-open").forEach(function (c) {
                    c.classList.remove("popup-open");
                });
                if (!wasOpen) cell.classList.add("popup-open");
            });
        }
        if (!calendarPopupDocBound) {
            calendarPopupDocBound = true;
            document.addEventListener("click", function () {
                if (!calendarDaysEl) return;
                calendarDaysEl.querySelectorAll(".calendar-cell.has-event.popup-open").forEach(function (c) {
                    c.classList.remove("popup-open");
                });
            });
        }
    }

    function renderCalendar() {
        if (!calendarDaysEl || !currentMonthEl) return;
        currentMonthEl.innerText = formatMonth(viewYear, viewMonth);
        calendarDaysEl.innerHTML = "";

        const firstDayOfMonth = new Date(viewYear, viewMonth, 1).getDay();
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        const totalCells = firstDayOfMonth + daysInMonth;
        const rows = Math.ceil(totalCells / 7);
        const cells = rows * 7;

        for (let i = 0; i < firstDayOfMonth; i++) {
            const emptyDay = document.createElement("div");
            emptyDay.className = "calendar-cell empty";
            calendarDaysEl.appendChild(emptyDay);
        }

        for (let day = 1; day <= daysInMonth; day++) {
            const dayEl = document.createElement("div");
            dayEl.className = "calendar-cell";
            const cellDate = document.createElement("div");
            cellDate.className = "cell-date";
            cellDate.innerText = String(day).padStart(2, "0");
            dayEl.appendChild(cellDate);

            if (day === currentDate) {
                // 仅当当前视图为“本月”时标记 today
                if (viewYear === today.getFullYear() && viewMonth === today.getMonth()) {
                    dayEl.classList.add("today");
                }
            }

            const dayEvents = allEventData.filter((event) => {
                const d = new Date(event.date);
                return (
                    d.getFullYear() === viewYear &&
                    d.getMonth() === viewMonth &&
                    d.getDate() === day
                );
            });

            if (dayEvents.length > 0) {
                dayEl.classList.add("has-event");
                const evLine = document.createElement("div");
                evLine.className = "cell-event";
                evLine.innerText = dayEvents[0].title || "赛事";
                dayEl.appendChild(evLine);

                // 弹窗：展示当天赛事（取第一条做详情，其余在文案里提示）
                const main = dayEvents[0];
                const popup = document.createElement("div");
                popup.className = "event-popup";
                const title = document.createElement("div");
                title.className = "popup-title";
                title.textContent = main.title || "赛事";
                const info = document.createElement("div");
                info.className = "popup-info";
                const more = dayEvents.length > 1 ? `（同日共${dayEvents.length}项）` : "";
                info.innerHTML =
                    `举办时间：${escapeHtml(formatDateCN(main.date))}${more}<br>` +
                    `报名说明：${escapeHtml(main.desc || "暂无")}`;
                const btns = document.createElement("div");
                btns.className = "popup-btns";
                const pdfUrl = String(main.pdfUrl || "").trim();
                const webUrl = normalizeUrl(main.url);
                if (pdfUrl) {
                    const aPdf = document.createElement("a");
                    aPdf.className = "popup-btn btn-pdf";
                    aPdf.href = pdfUrl;
                    aPdf.setAttribute("download", "");
                    aPdf.textContent = "下载通知PDF";
                    btns.appendChild(aPdf);
                }
                if (webUrl) {
                    const aWeb = document.createElement("a");
                    aWeb.className = "popup-btn btn-website";
                    aWeb.href = webUrl;
                    aWeb.target = "_blank";
                    aWeb.rel = "noopener";
                    aWeb.textContent = "访问赛事官网";
                    btns.appendChild(aWeb);
                }
                popup.appendChild(title);
                popup.appendChild(info);
                if (btns.children.length) popup.appendChild(btns);
                dayEl.appendChild(popup);
            }

            // 计算列号，决定弹窗左右
            const colIndex0 = (firstDayOfMonth + (day - 1)) % 7;
            if (_isPopupLeft(colIndex0)) dayEl.classList.add("popup-left");

            calendarDaysEl.appendChild(dayEl);
        }

        // 填充月末空白，使日历网格完整
        const filled = firstDayOfMonth + daysInMonth;
        for (let i = filled; i < cells; i++) {
            const emptyDay = document.createElement("div");
            emptyDay.className = "calendar-cell empty";
            calendarDaysEl.appendChild(emptyDay);
        }
    }

    function initSearch() {
        if (!searchInput) return;
        searchInput.addEventListener("input", function () {
            const keyword = String(this.value || "").trim().toLowerCase();
            if (!keyword) {
                filteredEvents = allEventData.slice();
            } else {
                filteredEvents = allEventData.filter((e) => {
                    return (
                        String(e.title || "").toLowerCase().includes(keyword) ||
                        String(e.desc || "").toLowerCase().includes(keyword)
                    );
                });
            }
            currentPage = 1;
            renderEventList();
        });
    }

    function initPagination() {
        if (prevBtn) prevBtn.addEventListener("click", function () {
            if (currentPage > 1) {
                currentPage--;
                renderEventList();
            }
        });
        if (nextBtn) nextBtn.addEventListener("click", function () {
            const totalPages = Math.ceil(filteredEvents.length / PAGE_SIZE) || 1;
            if (currentPage < totalPages) {
                currentPage++;
                renderEventList();
            }
        });
    }

    async function init() {
        // 无论接口是否成功，都先渲染完整日历（用样式区分是否有赛事）
        _ensureCalendarSelectors();
        initCalendarPopupInteractions();
        setViewMonth(viewYear, viewMonth);
        renderCalendar();
        if (yearSel) yearSel.addEventListener("change", function () {
            const y = parseInt(String(yearSel.value || ""), 10);
            if (!isNaN(y)) setViewMonth(y, viewMonth);
        });
        if (monthSel) monthSel.addEventListener("change", function () {
            const m = parseInt(String(monthSel.value || ""), 10);
            if (!isNaN(m)) setViewMonth(viewYear, Math.max(0, Math.min(11, m - 1)));
        });
        if (prevMonthBtn) prevMonthBtn.addEventListener("click", function () { shiftMonth(-1); });
        if (nextMonthBtn) nextMonthBtn.addEventListener("click", function () { shiftMonth(1); });
        try {
            await fetchEvents();
            renderCalendar();
            initSearch();
            initPagination();
            renderEventList();
        } catch (e) {
            // 接口失败时仍保留日历（无赛事高亮）
            try { renderCalendar(); } catch (e2) {}
            if (eventListEl) {
                eventListEl.innerHTML = `<div class="empty-tip" style="color:#e53e3e">获取赛事数据失败：${escapeHtml(e.message)}</div>`;
            }
        }
    }

    init();
})();

