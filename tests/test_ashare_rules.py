"""
A 股规则单元测试
覆盖：
  - is_a_share 识别
  - A 股 / 美股 news routing
  - A 股 News Agent 工具暴露控制
  - MarketRuleValidator：T+1、价格限制、无价格不误报、ST/停牌检测、美股 bypass
"""
import unittest
from unittest.mock import MagicMock, patch

from tradingagents.agents.utils.agent_utils import (
    MarketRuleValidator,
    is_a_share,
)


class IsAShareTests(unittest.TestCase):
    """is_a_share() 应正确识别 A 股与非 A 股标的。"""

    def test_a_share_sz(self):
        self.assertTrue(is_a_share("000001.SZ"))

    def test_a_share_sh(self):
        self.assertTrue(is_a_share("600519.SH"))

    def test_a_share_chinext(self):
        self.assertTrue(is_a_share("300750.SZ"))

    def test_a_share_star(self):
        self.assertTrue(is_a_share("688981.SH"))

    def test_us_stock_aapl(self):
        self.assertFalse(is_a_share("AAPL"))

    def test_us_stock_nvda(self):
        self.assertFalse(is_a_share("NVDA"))

    def test_hk_stock(self):
        self.assertFalse(is_a_share("00700.HK"))


class TickerResolverSZClassificationTests(unittest.TestCase):
    """
    TickerResolver bug fix: 000xxx.SZ 应为 CN_STOCK，不应被误判为 CN_INDEX。
    深交所无 000xxx 指数，SZ 指数均以 399xxx 开头。
    """

    def setUp(self):
        from tradingagents.agents.utils.agent_utils import get_market_type
        self.get_market_type = get_market_type

    def test_000100_sz_is_cn_stock(self):
        """TCL科技 000100.SZ 应为 CN_STOCK，非 CN_INDEX。"""
        self.assertEqual(self.get_market_type("000100.SZ"), "CN_STOCK")

    def test_000001_sz_is_cn_stock(self):
        """平安银行 000001.SZ 应为 CN_STOCK。"""
        self.assertEqual(self.get_market_type("000001.SZ"), "CN_STOCK")

    def test_000002_sz_is_cn_stock(self):
        """万科A 000002.SZ 应为 CN_STOCK。"""
        self.assertEqual(self.get_market_type("000002.SZ"), "CN_STOCK")

    def test_399006_sz_is_cn_index(self):
        """创业板指 399006.SZ 应仍为 CN_INDEX（399xxx 是真正的 SZ 指数）。"""
        self.assertEqual(self.get_market_type("399006.SZ"), "CN_INDEX")

    def test_000001_sh_is_cn_index(self):
        """上证综指 000001.SH 应仍为 CN_INDEX（SH 000xxx 是真正的上证指数）。"""
        self.assertEqual(self.get_market_type("000001.SH"), "CN_INDEX")


class NewsRoutingTests(unittest.TestCase):
    """
    get_news() 路由测试：
      - A 股 → 走 _get_news_ashare，不走 route_to_vendor
      - 美股 → 走 route_to_vendor，不进 _get_news_ashare
    """

    def _call_get_news(self, ticker):
        """通过 tool 调用底层函数（绕过 LangChain @tool 包装）。"""
        from tradingagents.agents.utils import news_data_tools as ndt
        return ndt.get_news.func(ticker, "2026-01-01", "2026-01-07")

    def test_a_share_routes_to_ashare_impl(self):
        """A 股 get_news() 应调用 _get_news_ashare，而非 route_to_vendor。"""
        from tradingagents.agents.utils import news_data_tools as ndt

        with patch.object(ndt, "_get_news_ashare", return_value="ASHARE_RESULT") as mock_fn, \
             patch.object(ndt, "route_to_vendor") as mock_route:
            result = self._call_get_news("000001.SZ")

        mock_fn.assert_called_once_with("000001.SZ", "2026-01-01", "2026-01-07")
        mock_route.assert_not_called()
        self.assertEqual(result, "ASHARE_RESULT")

    def test_us_stock_routes_to_vendor(self):
        """美股 get_news() 应调用 route_to_vendor，不进 _get_news_ashare。"""
        from tradingagents.agents.utils import news_data_tools as ndt

        with patch.object(ndt, "route_to_vendor", return_value="US_RESULT") as mock_route, \
             patch.object(ndt, "_get_news_ashare") as mock_fn:
            result = self._call_get_news("AAPL")

        mock_route.assert_called_once_with("get_news", "AAPL", "2026-01-01", "2026-01-07")
        mock_fn.assert_not_called()
        self.assertEqual(result, "US_RESULT")


class NewsAshareImplTests(unittest.TestCase):
    """_get_news_ashare() 内部行为测试（mock AKShare）。"""

    def test_akshare_success_returns_real_news(self):
        """AKShare 返回有效数据时，输出应包含真实新闻标题。"""
        import pandas as pd
        from tradingagents.agents.utils.news_data_tools import _get_news_ashare

        mock_df = pd.DataFrame([{
            "关键词": "000001",
            "新闻标题": "平安银行一季度净利润增长10%",
            "新闻内容": "平安银行披露一季报，净利润同比增长10%。",
            "发布时间": "2026-01-05 10:00:00",
            "文章来源": "东方财富",
            "新闻链接": "http://example.com/news/1",
        }])

        with patch("akshare.stock_news_em", return_value=mock_df):
            result = _get_news_ashare("000001.SZ", "2026-01-01", "2026-01-07")

        self.assertIn("平安银行一季度净利润增长10%", result)
        self.assertIn("东方财富", result)
        # 绝对不含虚构内容标志
        self.assertNotIn("北向资金近期持续净流入", result)

    def test_akshare_empty_df_falls_back_safely(self):
        """AKShare 返回空 DataFrame 时，输出为安全 fallback，不含虚构内容。"""
        import pandas as pd
        from tradingagents.agents.utils.news_data_tools import _get_news_ashare

        with patch("akshare.stock_news_em", return_value=pd.DataFrame()):
            result = _get_news_ashare("000001.SZ", "2026-01-01", "2026-01-07")

        self.assertIn("未获取到实时 A 股新闻", result)
        self.assertNotIn("平安银行", result)

    def test_akshare_exception_falls_back_safely(self):
        """AKShare 抛异常时，输出为安全 fallback，不崩溃，不含虚构内容。"""
        from tradingagents.agents.utils.news_data_tools import _get_news_ashare

        with patch("akshare.stock_news_em", side_effect=Exception("network error")):
            result = _get_news_ashare("600519.SH", "2026-01-01", "2026-01-07")

        self.assertIn("未获取到实时 A 股新闻", result)

    def test_akshare_import_error_falls_back_safely(self):
        """akshare 未安装时，输出为安全 fallback，不崩溃。"""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "akshare":
                raise ImportError("No module named 'akshare'")
            return real_import(name, *args, **kwargs)

        from tradingagents.agents.utils.news_data_tools import _get_news_ashare
        with patch("builtins.__import__", side_effect=fake_import):
            result = _get_news_ashare("000001.SZ", "2026-01-01", "2026-01-07")

        self.assertIn("未获取到实时 A 股新闻", result)

    def test_fallback_contains_no_fabricated_markers(self):
        """安全 fallback 不含任何旧版伪造新闻标志词。"""
        from tradingagents.agents.utils.news_data_tools import _safe_fallback

        output = _safe_fallback("000001.SZ", "2026-01-01", "2026-01-10")
        fabricated = [
            "货币政策委员会",
            "关于加强上市公司监管",
            "大规模设备更新",
            "北向资金近期持续净流入",
        ]
        for marker in fabricated:
            self.assertNotIn(marker, output, f"fallback 不应含虚构词: {marker}")

    def test_fallback_never_contains_global_news_content(self):
        """安全 fallback 严禁混入 US/全球新闻内容。"""
        from tradingagents.agents.utils.news_data_tools import _safe_fallback

        output = _safe_fallback("000001.SZ", "2026-01-01", "2026-01-10")
        global_news_markers = ["Federal Reserve", "NASDAQ", "S&P 500", "Dow Jones"]
        for marker in global_news_markers:
            self.assertNotIn(marker, output)


class NewsAgentToolExposureTests(unittest.TestCase):
    """News Agent 工具暴露控制：A 股不暴露 get_global_news。"""

    def test_a_share_does_not_expose_get_global_news(self):
        from tradingagents.agents.utils.news_data_tools import get_global_news, get_news

        ticker = "000001.SZ"
        tools = [get_news] if is_a_share(ticker) else [get_news, get_global_news]
        tool_names = [t.name for t in tools]
        self.assertNotIn("get_global_news", tool_names)

    def test_us_stock_exposes_get_global_news(self):
        from tradingagents.agents.utils.news_data_tools import get_global_news, get_news

        ticker = "AAPL"
        tools = [get_news] if is_a_share(ticker) else [get_news, get_global_news]
        tool_names = [t.name for t in tools]
        self.assertIn("get_global_news", tool_names)


class MarketRuleValidatorT1Tests(unittest.TestCase):
    """T+1 规则检测。"""

    def setUp(self):
        self.v = MarketRuleValidator("000001.SZ", prev_close=10.00)

    def test_t1_violation_chinese_flagged(self):
        plan = "建议当天买入并卖出以锁定利润。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("T+1 规则", result)

    def test_t1_violation_english_flagged(self):
        plan = "Intraday trade strategy: buy at open, sell at close."
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("T+1 规则", result)

    def test_t0_keyword_flagged(self):
        plan = "采用 T+0 策略，当日回转交易。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("A 股规则警告", result)

    def test_suspension_keyword_flagged(self):
        plan = "建议买入，该股票目前停牌，待复牌后操作。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("A 股规则警告", result)
        self.assertIn("停牌", result)

    def test_st_keyword_flagged(self):
        plan = "买入 *ST 某某，等待重组。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("A 股规则警告", result)

    def test_delisting_risk_flagged(self):
        plan = "该股有退市风险，建议短线博反弹。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertIn("A 股规则警告", result)

    def test_normal_plan_unchanged(self):
        plan = "建议逢低分批买入，目标持有3个月。"
        result = self.v.validate_and_rewrite_plan(plan)
        self.assertEqual(result, plan)


class MarketRuleValidatorPriceTests(unittest.TestCase):
    """价格限制校验。"""

    def test_price_over_limit_flagged(self):
        """主板 prev_close=10.00，¥12.00 超出 +10% 上限。"""
        v = MarketRuleValidator("000001.SZ", prev_close=10.00)
        result = v.validate_and_rewrite_plan("建议以¥12.00买入，止损设在¥9.00。")
        self.assertIn("A 股规则警告", result)
        self.assertIn("超出当日涨跌停", result)

    def test_price_in_range_no_warning(self):
        """主板 prev_close=10.00，¥10.50 在范围内，不产生警告。"""
        v = MarketRuleValidator("000001.SZ", prev_close=10.00)
        plan = "建议以¥10.50买入，止损设在¥9.50。"
        result = v.validate_and_rewrite_plan(plan)
        self.assertEqual(result, plan)

    def test_no_price_no_warning(self):
        """计划文本中无明确价格，不产生伪警告。"""
        v = MarketRuleValidator("000001.SZ", prev_close=10.00)
        plan = "建议逢低买入，目标持有3个月，关注基本面改善。"
        result = v.validate_and_rewrite_plan(plan)
        self.assertEqual(result, plan)

    def test_prev_close_none_skips_price_check(self):
        """prev_close=None 时，不做价格校验，不崩溃。"""
        v = MarketRuleValidator("000001.SZ", prev_close=None)
        plan = "建议以¥15.00买入。"
        result = v.validate_and_rewrite_plan(plan)
        self.assertNotIn("超出当日涨跌停", result)

    def test_chinext_board_limit_is_20pct(self):
        """创业板 prev_close=10.00，¥12.00 应在 ±20% 内，不产生价格警告。"""
        v = MarketRuleValidator("300750.SZ", prev_close=10.00)
        plan = "建议以¥12.00买入。"
        result = v.validate_and_rewrite_plan(plan)
        self.assertNotIn("超出当日涨跌停", result)

    def test_star_board_limit_is_20pct(self):
        """科创板 prev_close=10.00，¥11.50 应在 ±20% 内，不产生价格警告。"""
        v = MarketRuleValidator("688981.SH", prev_close=10.00)
        plan = "建议以¥11.50买入。"
        result = v.validate_and_rewrite_plan(plan)
        self.assertNotIn("超出当日涨跌停", result)


class USStockBypassTests(unittest.TestCase):
    """美股路径：MarketRuleValidator 应原样返回，无任何修改。"""

    def test_us_stock_plan_unchanged(self):
        v = MarketRuleValidator("AAPL", prev_close=200.00)
        plan = "Buy AAPL at $210, stop loss at $195. Intraday trade strategy."
        self.assertEqual(v.validate_and_rewrite_plan(plan), plan)

    def test_us_stock_t0_phrase_ignored(self):
        v = MarketRuleValidator("NVDA", prev_close=900.00)
        plan = "T+0 intraday strategy: buy open, sell close."
        self.assertEqual(v.validate_and_rewrite_plan(plan), plan)

    def test_us_stock_over_price_ignored(self):
        """美股无涨跌停限制，超出任何价格都不产生警告。"""
        v = MarketRuleValidator("TSLA", prev_close=200.00)
        plan = "Buy TSLA at $300."
        self.assertEqual(v.validate_and_rewrite_plan(plan), plan)


if __name__ == "__main__":
    unittest.main()
