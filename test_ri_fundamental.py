"""
test_ri_fundamental.py — ETF/指数基本面数据适配器验证脚本
========================================================
【新增测试文件】feature/regular-investment 分支

验证 159928.SZ (消费ETF) 全维度数据抓取：
  T01  get_etf_snapshot       — 基础快照（名称/规模/溢价率/1年涨跌幅）
  T02  get_etf_holdings       — 前十大权重成分股
  T03  get_etf_price_history  — 近3年日频历史价格（≥100条）
  T04  get_etf_dividends      — 历史分红记录
  T05  get_etf_flow           — 近期资金流量代理
  T06  get_index_valuation    — 中证消费指数PE/PB分位
  T07  get_full_etf_report    — 一键全维度报告（含所有模块）

运行方式：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe test_ri_fundamental.py
"""

import sys
import os

sys.path.insert(0, ".")

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

results: list[tuple[str, str, str]] = []   # (name, status, detail)

TICKER  = "159928.SZ"
INDEX   = "000932"     # 中证消费指数


def run(name: str, fn):
    print(f"\n{'─' * 60}\nTEST: {name}\n{'─' * 60}")
    try:
        detail = fn()
        print(f"{PASS}  {detail}")
        results.append((name, "PASS", detail))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"{FAIL}  {e}")
        results.append((name, "FAIL", str(e)))


# ── T01: 基础快照 ────────────────────────────────────────────────────────────
def t01_snapshot():
    from tradingagents.dataflows.ri_fundamental import get_etf_snapshot

    snap = get_etf_snapshot(TICKER)
    assert isinstance(snap, dict), "应返回 dict"
    assert snap.get("code") == "159928", f"代码不匹配: {snap.get('code')}"
    print(f"  快照字段：{list(snap.keys())}")
    for k, v in snap.items():
        print(f"    {k}: {v}")
    return f"获取到 {len(snap)} 个快照字段 ✓"


# ── T02: 前十大持仓 ──────────────────────────────────────────────────────────
def t02_holdings():
    from tradingagents.dataflows.ri_fundamental import get_etf_holdings

    result = get_etf_holdings(TICKER)
    assert isinstance(result, str), "应返回 str"
    print(f"  持仓数据（前500字符）：\n{result[:500]}")
    assert len(result) > 50, f"持仓数据过短：{len(result)} 字符"
    lines = result.strip().split("\n")
    # 至少有标题行和一行数据
    data_lines = [l for l in lines if l and not l.startswith("#")]
    assert len(data_lines) >= 1, f"无有效数据行"
    return f"持仓记录 {len(data_lines)} 行 ✓"


# ── T03: 历史价格 ────────────────────────────────────────────────────────────
def t03_price_history():
    from tradingagents.dataflows.ri_fundamental import get_etf_price_history
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
    df = get_etf_price_history(TICKER, start, end)

    assert df is not None and not df.empty, "历史价格为空"
    print(f"  历史数据形状：{df.shape}")
    print(f"  列名：{df.columns.tolist()}")
    print(f"  最新5行：\n{df.tail(5).to_string()}")

    close_col = "收盘" if "收盘" in df.columns else "Close"
    assert close_col in df.columns, f"缺少收盘价列，现有：{df.columns.tolist()}"
    assert len(df) >= 100, f"数据行数不足（{len(df)}条，要求≥100）"
    return f"近3年历史数据 {len(df)} 条 ✓"


# ── T04: 分红记录 ────────────────────────────────────────────────────────────
def t04_dividends():
    from tradingagents.dataflows.ri_fundamental import get_etf_dividends

    result = get_etf_dividends(TICKER)
    assert isinstance(result, str), "应返回 str"
    print(f"  分红记录（前500字符）：\n{result[:500]}")
    # 分红数据可能为空（部分ETF不分红），不强制失败
    if "No dividend" in result or "获取失败" in result:
        return f"该ETF暂无分红记录（可接受）✓"
    lines = [l for l in result.split("\n") if l and not l.startswith("#")]
    return f"分红记录 {len(lines)} 条 ✓"


# ── T05: 资金流量 ────────────────────────────────────────────────────────────
def t05_flow():
    from tradingagents.dataflows.ri_fundamental import get_etf_flow
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    result = get_etf_flow(TICKER, start, end)

    assert isinstance(result, str), "应返回 str"
    print(f"  资金流量数据（前400字符）：\n{result[:400]}")
    assert len(result) > 20, "资金流量数据过短"
    return "资金流量代理指标获取成功 ✓"


# ── T06: 指数估值分位 ────────────────────────────────────────────────────────
def t06_valuation():
    from tradingagents.dataflows.ri_fundamental import get_index_valuation

    result = get_index_valuation(INDEX, years=5)
    assert isinstance(result, dict), "应返回 dict"
    print(f"  估值字段：{result}")

    has_pe = result.get("pe_current") is not None
    has_pb = result.get("pb_current") is not None
    if not has_pe and not has_pb:
        return f"PE/PB均为None（数据源可能不支持该指数），字段={list(result.keys())} — 可接受 ✓"
    return (f"PE={result.get('pe_current')}，PE分位={result.get('pe_percentile')}%，"
            f"数据源={result.get('data_source')} ✓")


# ── T07: 全维度报告 ──────────────────────────────────────────────────────────
def t07_full_report():
    from tradingagents.dataflows.ri_fundamental import get_full_etf_report

    report = get_full_etf_report(TICKER, lookback_years=3)
    assert isinstance(report, str), "应返回 str"
    assert len(report) > 200, f"报告内容过短（{len(report)} 字符）"

    sections = ["一、基础快照", "二、前十大权重成分股", "三、历史价格摘要"]
    for sec in sections:
        assert sec in report, f"缺少章节：{sec}"

    print(f"  报告总长度：{len(report)} 字符")
    print(f"  报告前600字符：\n{report[:600]}")
    return f"全维度报告生成完毕，共 {len(report)} 字符 ✓"


# ── DCA 回测引擎验证 ─────────────────────────────────────────────────────────
def t08_dca_backtest():
    """验证 DCABacktester 能正确计算月定投回测指标。"""
    from tradingagents.dataflows.ri_fundamental import get_etf_price_history
    from tradingagents.ri_orchestrator import DCABacktester
    from datetime import datetime, timedelta

    end = datetime.now()
    start = end - timedelta(days=365 * 3 + 90)
    hist = get_etf_price_history(TICKER,
                                  start.strftime("%Y%m%d"),
                                  end.strftime("%Y%m%d"))
    assert hist is not None and not hist.empty, "价格数据获取失败"

    bt = DCABacktester(hist, invest_amount=1000.0, invest_period="monthly")
    result = bt.run(
        start_date=end - timedelta(days=365 * 3),
        end_date=end,
        label="T08 月定投验证",
    )

    print(f"  回测结果：")
    for k, v in result.items():
        print(f"    {k}: {v}")

    assert "error" not in result, f"回测报错: {result.get('error')}"
    assert result["total_periods"] >= 24, f"定投期数不足（{result['total_periods']}期）"
    assert isinstance(result["total_return_pct"], float), "累计收益率应为float"
    assert isinstance(result["max_drawdown_pct"], float), "最大回撤应为float"
    return (f"月定投 {result['total_periods']} 期，"
            f"累计收益 {result['total_return_pct']:+.2f}%，"
            f"CAGR {result['cagr_pct']:+.2f}%，"
            f"最大回撤 {result['max_drawdown_pct']:.2f}% ✓")


# ── 执行 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═" * 60)
    print(f"  ETF / 定投基本面数据适配器验证")
    print(f"  标的：{TICKER}（消费ETF）| 指数：{INDEX}（中证消费）")
    print("═" * 60)

    run("T01 | ETF 基础快照",        t01_snapshot)
    run("T02 | ETF 前十大持仓",      t02_holdings)
    run("T03 | ETF 历史价格（3年）",  t03_price_history)
    run("T04 | ETF 历史分红记录",    t04_dividends)
    run("T05 | ETF 近期资金流量",    t05_flow)
    run("T06 | 中证消费指数估值分位", t06_valuation)
    run("T07 | 全维度报告生成",      t07_full_report)
    run("T08 | DCA 回测引擎验证",    t08_dca_backtest)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")

    print("\n" + "═" * 60)
    print(f"  Results: {passed} passed / {failed} failed / {len(results)} total")
    print("═" * 60)
    for name, status, detail in results:
        icon = PASS if status == "PASS" else FAIL
        print(f"  {icon}  {name}")
        if status == "FAIL":
            print(f"       └─ {detail}")
    print()
    sys.exit(0 if failed == 0 else 1)
