"""
ri_fundamental.py — ETF / 指数专属基本面数据适配器
=====================================================
【新增模块】feature/regular-investment 分支专属文件
本文件不修改任何原生代码，仅提供定投分析所需的数据接口。

数据源优先级
-----------
1. AKShare  —— 免费开源，A股ETF/指数支持最完善（首选）
2. yfinance —— 作为部分数据的补充

支持的标的格式
-----------
  159928.SZ  →  消费ETF（sz159928）
  510300.SH  →  沪深300ETF
  000932.SH  →  中证消费指数（纯指数，非ETF）

主要对外接口
-----------
  get_etf_snapshot(ticker)             → dict   基础快照（规模/净值/溢价率）
  get_etf_holdings(ticker, date)       → str    前十大权重成分股 (CSV)
  get_etf_price_history(ticker, start, end) → pd.DataFrame  日频净值/收盘价
  get_etf_dividends(ticker)            → str    分红记录
  get_etf_flow(ticker, start, end)     → str    申赎净流量（份额变动）
  get_index_valuation(index_code, years) → dict PE/PB/PS 当前值 & 历史分位
  get_index_components_fundamentals(index_code) → str  成分股加权ROE/盈利增速
  get_full_etf_report(ticker)          → str    一键拉取全维度报告文本
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _progress(message: str) -> None:
    """Print a lightweight progress line for RI CLI runs."""
    print(f"    · {message}")

# ── 内部工具 ────────────────────────────────────────────────────────────────

def _code_and_exchange(ticker: str) -> tuple[str, str]:
    """
    解析 ticker → (6位纯代码, 交易所前缀)
    '159928.SZ' → ('159928', 'sz')
    '510300.SH' → ('510300', 'sh')
    '000932'    → ('000932', 'sh')   # 默认上交所（指数以0开头）
    """
    t = ticker.strip().upper()
    if "." in t:
        code, exch = t.rsplit(".", 1)
        prefix = "sz" if exch == "SZ" else "sh"
    else:
        code = t
        prefix = "sz" if t.startswith(("1", "3", "15", "16")) else "sh"
    return code, prefix


def _ak_safe(func_name: str, **kwargs):
    """安全调用 AKShare 函数，返回 None 而非抛出异常。"""
    try:
        import akshare as ak
        fn = getattr(ak, func_name)
        return fn(**kwargs)
    except Exception as e:
        logger.warning("AKShare %s(%s) failed: %s", func_name, kwargs, e)
        return None


def _retry(func, retries=3, delay=2):
    """简单重试装饰器（直接调用）。"""
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            if attempt < retries - 1:
                logger.warning("Retry %d/%d: %s", attempt + 1, retries, e)
                time.sleep(delay)
            else:
                raise


# ── 1. ETF 基础快照 ─────────────────────────────────────────────────────────

def get_etf_snapshot(ticker: str) -> dict:
    """
    返回 ETF/基金基本信息快照：
      name, code, exchange, latest_nav, latest_price,
      premium_rate(%), aum_cny, tracking_error(%), inception_date
    """
    code, prefix = _code_and_exchange(ticker)
    result: dict = {
        "ticker": ticker.upper(),
        "code": code,
        "exchange": prefix.upper(),
    }

    # ── 1a. 东财 ETF 基金信息 ──────────────────────────────────────────────
    info = _ak_safe("fund_etf_fund_info_em", fund=code)
    if info is not None and not info.empty:
        info_dict = dict(zip(info.iloc[:, 0], info.iloc[:, 1])) if info.shape[1] >= 2 else {}
        result["name"]           = info_dict.get("基金全称", info_dict.get("基金简称", f"ETF_{code}"))
        result["inception_date"] = info_dict.get("成立日期", "N/A")
        result["management"]     = info_dict.get("基金管理人", "N/A")
        result["tracking_index"] = info_dict.get("跟踪指数", "N/A")
        result["tracking_error"] = info_dict.get("跟踪误差", "N/A")
        aum_str = info_dict.get("资产规模", "N/A")
        result["aum_raw"] = aum_str

    # ── 1b. 实时行情（最新净值 & 价格） ──────────────────────────────────
    spot = _ak_safe("fund_etf_spot_em")
    if spot is not None and not spot.empty:
        row = spot[spot["代码"] == code] if "代码" in spot.columns else pd.DataFrame()
        if not row.empty:
            r = row.iloc[0]
            result["latest_price"]  = float(r.get("最新价", 0) or 0)
            result["latest_nav"]    = float(r.get("单位净值", r.get("最新价", 0)) or 0)
            result["aum_cny"]       = float(str(r.get("资产规模(亿元)", 0)).replace(",", "") or 0) * 1e8
            result["name"]          = r.get("名称", result.get("name", f"ETF_{code}"))
            nav = result.get("latest_nav", 0) or 0
            price = result.get("latest_price", 0) or 0
            if nav > 0:
                result["premium_rate_pct"] = round((price - nav) / nav * 100, 4)

    # ── 1c. 近期历史净值（用于计算最近一年涨跌幅） ───────────────────────
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    hist = get_etf_price_history(ticker,
                                  start_date.strftime("%Y%m%d"),
                                  end_date.strftime("%Y%m%d"))
    if hist is not None and not hist.empty and "收盘" in hist.columns:
        ret_1y = (hist["收盘"].iloc[-1] / hist["收盘"].iloc[0] - 1) * 100
        result["return_1y_pct"] = round(ret_1y, 2)
        result["price_52w_high"] = round(hist["收盘"].max(), 4)
        result["price_52w_low"]  = round(hist["收盘"].min(), 4)

    return result


# ── 2. ETF 持仓（前十大权重股） ─────────────────────────────────────────────

def get_etf_holdings(ticker: str, date: str = None) -> str:
    """
    返回 ETF 前十大权重成分股（CSV 格式字符串）。
    date: YYYYMMDD，默认取最近一个季报期。
    """
    code, _ = _code_and_exchange(ticker)

    if date is None:
        # 取最近季报期：3/31, 6/30, 9/30, 12/31
        today = datetime.now()
        quarter_ends = [(today.year, 3, 31), (today.year, 6, 30),
                        (today.year, 9, 30), (today.year, 12, 31)]
        past = [d for d in quarter_ends
                if datetime(d[0], d[1], d[2]) < today - timedelta(days=30)]
        if past:
            y, m, d_ = past[-1]
            date = f"{y}{m:02d}{d_:02d}"
        else:
            date = f"{today.year - 1}1231"

    df = _ak_safe("fund_etf_portfolio_hold_em", symbol=code, date=date)

    if df is None or df.empty:
        # 尝试上一季度
        try:
            prev = datetime.strptime(date, "%Y%m%d") - timedelta(days=91)
            date2 = prev.strftime("%Y%m%d")
            df = _ak_safe("fund_etf_portfolio_hold_em", symbol=code, date=date2)
        except Exception:
            pass

    if df is None or df.empty:
        return f"No holdings data found for {ticker} (date: {date})"

    header = (
        f"# {ticker.upper()} 前十大权重成分股（报告期：{date}）\n"
        f"# 数据来源：东方财富 / AKShare\n\n"
    )
    return header + df.head(10).to_csv(index=False)


# ── 3. ETF 历史价格（日频） ──────────────────────────────────────────────────

def get_etf_price_history(ticker: str,
                           start_date: str = None,
                           end_date: str = None) -> Optional[pd.DataFrame]:
    """
    返回 ETF 历史日频 OHLCV + 涨跌幅 DataFrame。
    start_date / end_date: YYYYMMDD 格式。
    """
    code, _ = _code_and_exchange(ticker)

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")

    # 东财日K 接口（adjust="" 不复权，adjust="hfq" 后复权）
    df = _ak_safe("fund_etf_hist_em",
                  symbol=code,
                  period="daily",
                  start_date=start_date,
                  end_date=end_date,
                  adjust="hfq")   # 后复权，适合长期回测

    if df is None or df.empty:
        _progress(f"{ticker} 的 AKShare ETF 行情获取失败，切换到 yfinance 备用源")
        # fallback: yfinance
        try:
            import yfinance as yf
            from tradingagents.dataflows.stockstats_utils import normalize_ticker_yf
            yf_sym = normalize_ticker_yf(ticker)
            t = yf.Ticker(yf_sym)
            start_dt = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
            end_dt   = datetime.strptime(end_date,   "%Y%m%d").strftime("%Y-%m-%d")
            hist = t.history(start=start_dt, end=end_dt)
            if not hist.empty:
                hist = hist.reset_index()
                hist.rename(columns={"Date": "日期", "Close": "收盘",
                                     "Open": "开盘", "High": "最高",
                                     "Low": "最低", "Volume": "成交量"}, inplace=True)
                _progress(f"{ticker} 的 yfinance 备用行情获取成功，共 {len(hist)} 条记录")
                return hist
        except Exception:
            pass
        _progress(f"{ticker} 的 yfinance 备用行情也未返回有效数据")

    return df


# ── 4. 分红记录 ─────────────────────────────────────────────────────────────

def get_etf_dividends(ticker: str) -> str:
    """返回 ETF 历史分红记录（CSV）。"""
    code, _ = _code_and_exchange(ticker)

    df = _ak_safe("fund_open_fund_info_em", fund=code, indicator="分红送配")

    if df is None or df.empty:
        # 尝试东财基金分红接口
        df = _ak_safe("fund_etf_dividend_em", symbol=code)

    if df is None or df.empty:
        return f"No dividend records found for {ticker} (AKShare)"

    header = (
        f"# {ticker.upper()} 历史分红记录\n"
        f"# 数据来源：AKShare\n\n"
    )
    return header + df.to_csv(index=False)


# ── 5. ETF 申赎净流量（份额变化） ───────────────────────────────────────────

def get_etf_flow(ticker: str,
                 start_date: str = None,
                 end_date: str = None) -> str:
    """
    返回 ETF 近期申赎净流量数据（份额变动，亿份/亿元）。
    数据来源：AKShare fund_etf_hist_em 中的 成交额 字段辅助判断，
    以及 fund_etf_scale_change_em（若可用）。
    """
    code, _ = _code_and_exchange(ticker)

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    # 尝试申购赎回数据
    df = _ak_safe("fund_etf_fund_info_em", fund=code)

    # 规模变动代理：取最近90天日频数据的成交额变化
    hist = _ak_safe("fund_etf_hist_em",
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="")
    if hist is None or hist.empty:
        return f"No flow data available for {ticker}"

    # 计算 20日成交额滚动均值作为流量参考
    if "成交额" in hist.columns:
        hist["成交额_20MA"] = hist["成交额"].rolling(20).mean()
        hist["资金热度"] = (hist["成交额"] / hist["成交额_20MA"]).round(2)

    header = (
        f"# {ticker.upper()} 近期资金流量代理指标\n"
        f"# 注：A股ETF精细申赎数据需基金公司公告，此处以成交额变化为代理指标\n"
        f"# 数据来源：AKShare\n\n"
    )
    cols = [c for c in ["日期", "收盘", "成交量", "成交额", "成交额_20MA", "资金热度"] if c in hist.columns]
    return header + hist[cols].tail(30).to_csv(index=False)


# ── 6. 指数估值（PE / PB 历史分位） ─────────────────────────────────────────

def get_index_valuation(index_code: str, years: int = 5) -> dict:
    """
    获取指数当前 PE/PB 估值及历史 N 年分位数。
    index_code: 指数代码，如 '000932' (中证消费)、'000300' (沪深300)
    """
    result: dict = {
        "index_code": index_code,
        "years": years,
        "pe_current": None,
        "pb_current": None,
        "pe_percentile": None,
        "pb_percentile": None,
        "data_source": "AKShare",
    }

    # ── 方法1：天天基金估值数据 ──────────────────────────────────────────
    df = _ak_safe("index_value_hist_funddb",
                  symbol=index_code,
                  indicator="市盈率")
    if df is not None and not df.empty:
        cutoff = datetime.now() - timedelta(days=years * 365)
        df["日期"] = pd.to_datetime(df["日期"] if "日期" in df.columns else df.columns[0],
                                     errors="coerce")
        df = df.dropna(subset=["日期"])
        pe_col = [c for c in df.columns if "市盈率" in c or "PE" in c.upper()]
        if pe_col:
            pe_col = pe_col[0]
            df[pe_col] = pd.to_numeric(df[pe_col], errors="coerce")
            df_hist = df[df["日期"] >= pd.Timestamp(cutoff)]
            if not df_hist.empty:
                result["pe_current"] = round(float(df_hist[pe_col].iloc[-1]), 2)
                result["pe_percentile"] = round(
                    (df_hist[pe_col] <= result["pe_current"]).mean() * 100, 1
                )

    # ── 方法2：用指数历史 + yfinance 粗估（fallback）─────────────────────
    if result["pe_current"] is None:
        try:
            import yfinance as yf
            # Map common A-share indices to Yahoo symbols
            yahoo_map = {
                "000300": "000300.SS",
                "000932": "000932.SS",
                "000905": "000905.SS",
                "000852": "000852.SS",
                "399006": "399006.SZ",
                "399001": "399001.SZ",
            }
            yahoo_sym = yahoo_map.get(index_code, f"{index_code}.SS")
            t = yf.Ticker(yahoo_sym)
            info = t.info or {}
            result["pe_current"]  = info.get("trailingPE")
            result["pb_current"]  = info.get("priceToBook")
            result["data_source"] = "yfinance (fallback)"
        except Exception:
            pass

    return result


# ── 7. 成分股基本面加权汇总 ─────────────────────────────────────────────────

def get_index_components_fundamentals(index_code: str) -> str:
    """
    获取指数成分股的加权平均基本面指标（ROE、净利润增速、营收增速）。
    使用 AKShare 获取成分股列表 + 逐股基本面数据，加权计算汇总。
    """
    # 获取指数成分股
    df_comp = _ak_safe("index_stock_cons_weight_csindex", symbol=index_code)
    if df_comp is None or df_comp.empty:
        df_comp = _ak_safe("index_stock_cons", symbol=index_code)

    if df_comp is None or df_comp.empty:
        return f"No component data found for index {index_code}"

    # 取权重最大的 top10 成分股做汇总
    weight_col = next((c for c in df_comp.columns if "权重" in c or "weight" in c.lower()), None)
    code_col   = next((c for c in df_comp.columns if "代码" in c or "code" in c.lower()), None)
    name_col   = next((c for c in df_comp.columns if "名称" in c or "name" in c.lower()), None)

    if code_col is None:
        return f"Cannot identify stock code column in component data for {index_code}"

    if weight_col:
        df_comp[weight_col] = pd.to_numeric(df_comp[weight_col], errors="coerce")
        df_top = df_comp.nlargest(10, weight_col)
    else:
        df_top = df_comp.head(10)

    # 汇总成分股基本面（使用AKShare的个股基本面接口）
    rows = []
    for _, row in df_top.iterrows():
        stock_code = str(row[code_col]).zfill(6)
        name = str(row[name_col]) if name_col else stock_code
        weight = float(row[weight_col]) if weight_col and pd.notna(row[weight_col]) else None

        try:
            from tradingagents.dataflows.akshare_fundamentals import get_fundamentals
            fun_text = get_fundamentals(f"{stock_code}.SH" if stock_code.startswith("6") else f"{stock_code}.SZ")
            rows.append({
                "成分股": name,
                "代码": stock_code,
                "权重(%)": round(weight, 2) if weight else "N/A",
                "基本面摘要": fun_text[:200] + "..." if len(fun_text) > 200 else fun_text,
            })
        except Exception:
            rows.append({"成分股": name, "代码": stock_code,
                         "权重(%)": round(weight, 2) if weight else "N/A", "基本面摘要": "N/A"})

    if not rows:
        return f"No fundamental data collected for {index_code} components"

    df_out = pd.DataFrame(rows)
    header = (
        f"# 指数 {index_code} 前十大成分股基本面汇总\n"
        f"# 数据来源：AKShare + 新浪财经\n\n"
    )
    return header + df_out.to_csv(index=False)


# ── 8. 一键全维度报告 ───────────────────────────────────────────────────────

def get_full_etf_report(ticker: str,
                         lookback_years: int = 3,
                         analysis_date: str = None) -> str:
    """
    拉取 ETF 全维度数据，返回结构化报告文本。
    包含：基础快照、持仓、估值分位、近期资金流量、分红记录。
    """
    if analysis_date is None:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    code, prefix = _code_and_exchange(ticker)
    sections: list[str] = [
        f"# {ticker.upper()} ETF 全维度数据报告",
        f"> 分析日期：{analysis_date}  |  数据来源：AKShare + yfinance",
        "",
    ]

    # 1. 基础快照
    try:
        snap = get_etf_snapshot(ticker)
        lines = [f"## 一、基础快照", ""]
        for k, v in snap.items():
            lines.append(f"- **{k}**: {v}")
        sections.append("\n".join(lines))
    except Exception as e:
        sections.append(f"## 一、基础快照\n> 获取失败：{e}")

    sections.append("---")

    # 2. 前十大持仓
    try:
        holdings = get_etf_holdings(ticker)
        sections.append(f"## 二、前十大权重成分股\n\n{holdings}")
    except Exception as e:
        sections.append(f"## 二、前十大权重成分股\n> 获取失败：{e}")

    sections.append("---")

    # 3. 价格历史摘要
    try:
        end_d = datetime.now().strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y%m%d")
        hist = get_etf_price_history(ticker, start_d, end_d)
        if hist is not None and not hist.empty:
            close_col = "收盘" if "收盘" in hist.columns else "Close"
            lines = ["## 三、历史价格摘要", ""]
            lines.append(f"- 分析区间：{start_d} ~ {end_d}（{lookback_years}年）")
            lines.append(f"- 总交易日数：{len(hist)}")
            lines.append(f"- 起始价格：{hist[close_col].iloc[0]:.4f}")
            lines.append(f"- 最新价格：{hist[close_col].iloc[-1]:.4f}")
            lines.append(f"- 区间最高：{hist[close_col].max():.4f}")
            lines.append(f"- 区间最低：{hist[close_col].min():.4f}")
            pct = (hist[close_col].iloc[-1] / hist[close_col].iloc[0] - 1) * 100
            lines.append(f"- 区间累计涨跌幅：{pct:.2f}%")
            # Max drawdown
            roll_max = hist[close_col].cummax()
            dd = (hist[close_col] - roll_max) / roll_max
            lines.append(f"- 区间最大回撤：{dd.min() * 100:.2f}%")
            sections.append("\n".join(lines))
        else:
            sections.append("## 三、历史价格摘要\n> 暂无历史价格数据")
    except Exception as e:
        sections.append(f"## 三、历史价格摘要\n> 获取失败：{e}")

    sections.append("---")

    # 4. 分红记录
    try:
        div = get_etf_dividends(ticker)
        sections.append(f"## 四、历史分红记录\n\n{div}")
    except Exception as e:
        sections.append(f"## 四、历史分红记录\n> 获取失败：{e}")

    sections.append("---")

    # 5. 近期资金流量
    try:
        flow_end = datetime.now().strftime("%Y%m%d")
        flow_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        flow = get_etf_flow(ticker, flow_start, flow_end)
        sections.append(f"## 五、近期资金流量（近90日）\n\n{flow}")
    except Exception as e:
        sections.append(f"## 五、近期资金流量\n> 获取失败：{e}")

    return "\n\n".join(sections)


# ── 9. A 股个股历史价格（DCA 回测用） ────────────────────────────────────────

def get_stock_price_history(ticker: str,
                             start_date: str = None,
                             end_date: str = None) -> Optional[pd.DataFrame]:
    """
    返回 A 股个股日频历史价格 DataFrame（列名与 ETF 版对齐：日期/收盘）。
    start_date / end_date: YYYYMMDD 格式。
    优先 AKShare stock_zh_a_hist（后复权），fallback yfinance。
    """
    code, _ = _code_and_exchange(ticker)

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")

    df = _ak_safe("stock_zh_a_hist",
                  symbol=code,
                  period="daily",
                  start_date=start_date,
                  end_date=end_date,
                  adjust="hfq")

    if df is not None and not df.empty:
        # AKShare 返回列名可能是"日期"/"收盘"，也可能是英文，统一处理
        col_map = {}
        for c in df.columns:
            if "日期" in c or c.lower() in ("date", "trade_date"):
                col_map[c] = "日期"
            elif "收盘" in c or c.lower() == "close":
                col_map[c] = "收盘"
        if col_map:
            df = df.rename(columns=col_map)
        return df

    # fallback: yfinance
    _progress(f"{ticker} 的 AKShare 个股行情获取失败，切换到 yfinance 备用源")
    try:
        import yfinance as yf
        from tradingagents.dataflows.stockstats_utils import normalize_ticker_yf
        yf_sym = normalize_ticker_yf(ticker)
        t = yf.Ticker(yf_sym)
        start_dt = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
        end_dt   = datetime.strptime(end_date,   "%Y%m%d").strftime("%Y-%m-%d")
        hist = t.history(start=start_dt, end=end_dt)
        if not hist.empty:
            hist = hist.reset_index()
            hist.rename(columns={"Date": "日期", "Close": "收盘"}, inplace=True)
            _progress(f"{ticker} 的 yfinance 备用行情获取成功，共 {len(hist)} 条记录")
            return hist
    except Exception:
        pass

    _progress(f"{ticker} 的 yfinance 备用行情也未返回有效数据")

    return None


# ── 10. A 股个股基础报告（定投 Step 1 用）────────────────────────────────────

def get_full_stock_report(ticker: str,
                           lookback_years: int = 3,
                           analysis_date: str = None) -> str:
    """
    为 A 股个股生成结构化基础报告文本（基本信息 + 历史价格摘要）。
    不依赖 ETF 专用接口。
    """
    if analysis_date is None:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    code, _ = _code_and_exchange(ticker)
    sections: list[str] = [
        f"# {ticker.upper()} A 股个股基础数据报告",
        f"> 分析日期：{analysis_date}  |  数据来源：AKShare + yfinance",
        "",
    ]

    # 1. 个股基本信息
    try:
        info_df = _ak_safe("stock_individual_info_em", symbol=code)
        lines = ["## 一、个股基本信息", ""]
        if info_df is not None and not info_df.empty:
            for _, row in info_df.iterrows():
                item = row.iloc[0] if len(row) > 0 else ""
                val  = row.iloc[1] if len(row) > 1 else ""
                lines.append(f"- **{item}**: {val}")
        else:
            lines.append(f"- 代码：{ticker}")
        sections.append("\n".join(lines))
    except Exception as e:
        sections.append(f"## 一、个股基本信息\n> 获取失败：{e}")

    sections.append("---")

    # 2. 历史价格摘要（与 ETF 版逻辑对称）
    try:
        end_d   = datetime.now().strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y%m%d")
        hist = get_stock_price_history(ticker, start_d, end_d)
        if hist is not None and not hist.empty:
            close_col = "收盘" if "收盘" in hist.columns else "Close"
            lines = ["## 二、历史价格摘要", ""]
            lines.append(f"- 分析区间：{start_d} ~ {end_d}（{lookback_years}年）")
            lines.append(f"- 总交易日数：{len(hist)}")
            lines.append(f"- 起始价格：{hist[close_col].iloc[0]:.4f}")
            lines.append(f"- 最新价格：{hist[close_col].iloc[-1]:.4f}")
            lines.append(f"- 区间最高：{hist[close_col].max():.4f}")
            lines.append(f"- 区间最低：{hist[close_col].min():.4f}")
            pct = (hist[close_col].iloc[-1] / hist[close_col].iloc[0] - 1) * 100
            lines.append(f"- 区间累计涨跌幅：{pct:.2f}%")
            roll_max = hist[close_col].cummax()
            dd = (hist[close_col] - roll_max) / roll_max
            lines.append(f"- 区间最大回撤：{dd.min() * 100:.2f}%")
            sections.append("\n".join(lines))
        else:
            sections.append("## 二、历史价格摘要\n> 暂无历史价格数据")
    except Exception as e:
        sections.append(f"## 二、历史价格摘要\n> 获取失败：{e}")

    sections.append("---")

    # 3. 基本面摘要（复用现有 akshare_fundamentals 接口）
    try:
        from tradingagents.dataflows.akshare_fundamentals import get_fundamentals
        fund_text = get_fundamentals(ticker)
        sections.append(f"## 三、基本面摘要\n\n{fund_text}")
    except Exception as e:
        sections.append(f"## 三、基本面摘要\n> 获取失败：{e}")

    return "\n\n".join(sections)


# ── 11. 指数基础报告（定投 Step 1 用）────────────────────────────────────────

def get_full_index_report(ticker: str,
                           lookback_years: int = 3,
                           analysis_date: str = None) -> str:
    """
    为宽基/行业指数生成结构化基础报告文本（估值分位 + 成分股 + 价格摘要）。
    price 数据复用 get_etf_price_history（指数可通过 yfinance fallback 获取）。
    """
    if analysis_date is None:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    code, _ = _code_and_exchange(ticker)
    sections: list[str] = [
        f"# {ticker.upper()} 指数基础数据报告",
        f"> 分析日期：{analysis_date}  |  数据来源：AKShare + yfinance",
        "",
    ]

    # 1. 估值分位
    try:
        val = get_index_valuation(code, lookback_years)
        lines = ["## 一、指数估值（历史分位）", ""]
        for k, v in val.items():
            lines.append(f"- **{k}**: {v}")
        sections.append("\n".join(lines))
    except Exception as e:
        sections.append(f"## 一、指数估值\n> 获取失败：{e}")

    sections.append("---")

    # 2. 成分股基本面
    try:
        comp = get_index_components_fundamentals(code)
        sections.append(f"## 二、前十大成分股基本面\n\n{comp}")
    except Exception as e:
        sections.append(f"## 二、前十大成分股基本面\n> 获取失败：{e}")

    sections.append("---")

    # 3. 历史价格摘要（ETF 版 fallback 对指数也有 yfinance 路径）
    try:
        end_d   = datetime.now().strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y%m%d")
        hist = get_etf_price_history(ticker, start_d, end_d)
        if hist is not None and not hist.empty:
            close_col = "收盘" if "收盘" in hist.columns else "Close"
            lines = ["## 三、历史价格摘要", ""]
            lines.append(f"- 分析区间：{start_d} ~ {end_d}（{lookback_years}年）")
            lines.append(f"- 总交易日数：{len(hist)}")
            lines.append(f"- 起始价格：{hist[close_col].iloc[0]:.4f}")
            lines.append(f"- 最新价格：{hist[close_col].iloc[-1]:.4f}")
            pct = (hist[close_col].iloc[-1] / hist[close_col].iloc[0] - 1) * 100
            lines.append(f"- 区间累计涨跌幅：{pct:.2f}%")
            sections.append("\n".join(lines))
        else:
            sections.append("## 三、历史价格摘要\n> 暂无历史价格数据")
    except Exception as e:
        sections.append(f"## 三、历史价格摘要\n> 获取失败：{e}")

    return "\n\n".join(sections)
