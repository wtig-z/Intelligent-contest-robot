#!/usr/bin/env python3
"""
本系统场景响应时间简易压测（可重复执行，用于论文表 3-x 数据支撑）。

用法：
  # 1）先启动 Web 服务（另开终端），例如：
  #    cd 项目根 && python run.py
  #    或 Docker 映射到本机 5000 端口
  # 2）再执行：
  export BASE_URL=http://127.0.0.1:5000
  export BENCH_USER=xxx BENCH_PASS=xxx   # 测登录与火山问答时必填
  python3 scripts/bench_response_times.py

说明：
  - 「火山知识库问答首包」统计 SSE 流式接口读到首段有效负载的耗时（依赖外网与模型，波动大）。
  - 未配置 BENCH_USER 或火山未就绪时对应行会标记为跳过。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Tuple


def _preflight_health(base: str) -> Optional[str]:
    """若服务不可达，返回给人看的说明；否则返回 None。"""
    url = f"{base}/api/health"
    try:
        urllib.request.urlopen(url, timeout=5)
        return None
    except urllib.error.URLError as e:
        err = str(e.reason) if getattr(e, "reason", None) else str(e)
        if "Connection refused" in err or "111" in err:
            return (
                f"无法连接 {url}（Connection refused）。请先在另一终端启动后端，例如：\n"
                f"  cd 项目根目录 && python run.py\n"
                f"或确认 Docker 已映射端口、BASE_URL 是否正确（当前 BASE_URL={base}）。"
            )
        return f"无法访问 {url}: {err}"
    except Exception as e:
        return f"无法访问 {url}: {e}"


def _req(
    method: str,
    url: str,
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
    timeout: float = 120.0,
) -> Tuple[float, int, bytes]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=data, method=method)
    h = dict(headers or {})
    if data is not None and "Content-Type" not in {k.title(): v for k, v in h.items()}:
        pass  # caller sets
    for k, v in h.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        body = resp.read()
    dt = time.perf_counter() - t0
    return dt, status, body


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _bench(name: str, fn: Callable[[], float], n: int = 25) -> dict:
    vals: List[float] = []
    for _ in range(n):
        try:
            vals.append(fn())
        except Exception as e:
            return {"name": name, "error": str(e), "n": 0}
    vals.sort()
    return {
        "name": name,
        "n": n,
        "mean_ms": statistics.mean(vals) * 1000,
        "p50_ms": _percentile(vals, 50) * 1000,
        "p95_ms": _percentile(vals, 95) * 1000,
        "min_ms": vals[0] * 1000,
        "max_ms": vals[-1] * 1000,
    }


def main() -> int:
    base = os.getenv("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    n = int(os.getenv("BENCH_N", "25"))
    user = os.getenv("BENCH_USER", "").strip()
    pw = os.getenv("BENCH_PASS", "").strip()

    pre_err = _preflight_health(base)
    if pre_err:
        print(pre_err, file=sys.stderr)
        print(
            json.dumps(
                {
                    "base_url": base,
                    "error": "server_unreachable",
                    "message": pre_err,
                    "results": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    def health():
        dt, _, _ = _req("GET", f"{base}/api/health", timeout=30)
        return dt

    def events_list():
        dt, _, _ = _req("GET", f"{base}/api/events", timeout=30)
        return dt

    def page_volc_kb():
        dt, _, _ = _req("GET", f"{base}/volc-kb", timeout=60)
        return dt

    rows = [
        _bench("健康检查 /api/health", health, n),
        _bench("赛事列表 /api/events", events_list, n),
        _bench("火山问答页首屏 GET /volc-kb", page_volc_kb, min(n, 10)),
    ]

    token: Optional[str] = None
    if user and pw:
        try:
            body = json.dumps({"username": user, "password": pw}).encode("utf-8")
            dt, code, resp = _req(
                "POST",
                f"{base}/api/auth/login",
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            j = json.loads(resp.decode("utf-8"))
            if j.get("code") == 0 and j.get("data", {}).get("token"):
                token = j["data"]["token"]
                rows.append(
                    {
                        "name": "用户登录 POST /api/auth/login",
                        "n": 1,
                        "mean_ms": dt * 1000,
                        "p50_ms": dt * 1000,
                        "p95_ms": dt * 1000,
                        "min_ms": dt * 1000,
                        "max_ms": dt * 1000,
                    }
                )
            else:
                rows.append({"name": "用户登录", "error": j.get("message", "login failed"), "n": 0})
        except Exception as e:
            rows.append({"name": "用户登录", "error": str(e), "n": 0})
    else:
        rows.append(
            {
                "name": "用户登录",
                "error": "未设置 BENCH_USER/BENCH_PASS",
                "hint": "导出环境变量后再运行，例如: export BENCH_USER=你的用户名 BENCH_PASS=你的密码",
                "n": 0,
            }
        )

    # 火山 SSE 首包：读到第一个 data: 行块
    if token:
        try:
            body = json.dumps(
                {
                    "message": "你好",
                    "stream": True,
                    "history": [],
                    "deep_think": False,
                }
            ).encode("utf-8")

            def volc_ttft():
                t0 = time.perf_counter()
                req = urllib.request.Request(
                    f"{base}/api/volc_kb/chat",
                    data=body,
                    method="POST",
                )
                req.add_header("Content-Type", "application/json")
                req.add_header("Accept", "text/event-stream")
                req.add_header("Authorization", f"Bearer {token}")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    buf = b""
                    while time.perf_counter() - t0 < 120:
                        chunk = resp.read(256)
                        if not chunk:
                            break
                        buf += chunk
                        if b"data:" in buf or b"event:" in buf:
                            return time.perf_counter() - t0
                return time.perf_counter() - t0

            # 只跑 3 次，避免扣费与耗时过长
            ttft_vals = []
            for _ in range(3):
                try:
                    ttft_vals.append(volc_ttft())
                except Exception as e:
                    rows.append({"name": "火山知识库问答(SSE首包)", "error": str(e), "n": 0})
                    ttft_vals = []
                    break
            if ttft_vals:
                ttft_vals.sort()
                rows.append(
                    {
                        "name": "火山知识库问答 SSE 首包耗时",
                        "n": len(ttft_vals),
                        "mean_ms": statistics.mean(ttft_vals) * 1000,
                        "p50_ms": ttft_vals[len(ttft_vals) // 2] * 1000,
                        "p95_ms": ttft_vals[-1] * 1000,
                        "min_ms": ttft_vals[0] * 1000,
                        "max_ms": ttft_vals[-1] * 1000,
                    }
                )
        except Exception as e:
            rows.append({"name": "火山知识库问答", "error": str(e), "n": 0})

    print(json.dumps({"base_url": base, "iterations_default": n, "results": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
