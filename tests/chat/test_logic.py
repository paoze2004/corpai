"""
ChatService 纯逻辑方法特性测试

锁定当前行为(Phase 1 拆分前),拆分后这些测试必须继续通过。

覆盖:
- _should_skip_planning:启发式判断
- intent_agent 的 JSON 清理逻辑(strip_think + 去 fences + 抽取 JSON)
"""
import pytest
from CorpAI.core.chat import ChatService


class TestShouldSkipPlanning:
    """_should_skip_planning 启发式 — 锁定当前行为。

    关键行为(chat.py:449-482):
    1. len(intents) <= 1 → True(包括空、单个 intent、单个 complex/order)
    2. 多意图全部 in independent_intents set → True
    3. 多意图任一不在 set → False

    注意:文档说"order 需要 planning",但因为 len<=1 优先,单 order 实际跳过。
    """

    def setup_method(self):
        # 跳过 __init__(会创建 A2A network/DB 连接)— 此方法只读 self 上的独立 set 副本
        self.svc = ChatService.__new__(ChatService)

    # ─── 单意图 / 空 ───
    def test_empty_intents_returns_true(self):
        """空意图列表 → 跳过 planning"""
        assert self.svc._should_skip_planning([]) is True

    def test_single_known_intent_returns_true(self):
        """单个已知意图 → 跳过"""
        assert self.svc._should_skip_planning(["weather"]) is True
        assert self.svc._should_skip_planning(["flight"]) is True
        assert self.svc._should_skip_planning(["attraction"]) is True

    def test_single_complex_returns_true(self):
        """单个 complex → 跳过(len<=1 优先于 independent_intents set)"""
        assert self.svc._should_skip_planning(["complex"]) is True

    def test_single_order_returns_true(self):
        """单个 order → 跳过(同上,文档说 order 需要 planning 但代码不实现)"""
        assert self.svc._should_skip_planning(["order"]) is True

    def test_single_out_of_scope_returns_true(self):
        """单个 out_of_scope → 跳过"""
        assert self.svc._should_skip_planning(["out_of_scope"]) is True

    def test_single_unknown_returns_true(self):
        """单个 unknown intent → 跳过"""
        assert self.svc._should_skip_planning(["foobar"]) is True

    # ─── 多意图(全部独立) ───
    def test_multiple_all_independent_returns_true(self):
        """多意图全部独立 → 跳过"""
        assert self.svc._should_skip_planning(["weather", "flight"]) is True
        assert self.svc._should_skip_planning(["weather", "attraction", "tour_group"]) is True
        # 全部 9 个 independent_intents 都在
        all_independent = [
            "weather", "flight", "train", "concert", "attraction",
            "car_rental", "tour_group", "insurance", "trip_order"
        ]
        assert self.svc._should_skip_planning(all_independent) is True

    # ─── 多意图(含非独立) ───
    def test_multiple_with_complex_returns_false(self):
        """多意图含 complex → 不跳过"""
        assert self.svc._should_skip_planning(["weather", "complex"]) is False

    def test_multiple_with_order_returns_false(self):
        """多意图含 order → 不跳过"""
        assert self.svc._should_skip_planning(["weather", "order"]) is False

    def test_multiple_with_out_of_scope_returns_false(self):
        """多意图含 out_of_scope → 不跳过"""
        assert self.svc._should_skip_planning(["weather", "out_of_scope"]) is False

    def test_multiple_with_unknown_returns_false(self):
        """多意图含 unknown intent → 不跳过"""
        assert self.svc._should_skip_planning(["weather", "foobar"]) is False


class TestIntentJsonParsing:
    """intent_agent 的 JSON 清理逻辑 — 锁定当前行为。

    关键行为(chat.py:418-431):
    1. strip_think 去掉 <think>...</think>
    2. 去 ```json ... ``` fences
    3. 若不是 { 开头,正则贪婪抽取第一个 {.*} 子串
    4. json.loads 成功 → 取 intents/user_queries/follow_up_message
    5. json.loads 失败 → 返回 ([], {}, response)

    这里只测试清理逻辑(纯文本处理),不调 LLM。
    """

    # 通过复制 chat.py:425-431 的清理逻辑来验证
    @staticmethod
    def _clean_intent_response(text: str) -> str:
        """复制 chat.py:418-431 的清理逻辑(测试锁定目标)"""
        import re
        import json as _json
        from CorpAI.utils.format import strip_think
        text = strip_think(text)
        text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text).strip()
        if not text.startswith('{'):
            match = re.search(r'\{.*\}', text, flags=re.DOTALL)
            if match:
                text = match.group(0)
        return text

    def test_clean_think_blocks(self):
        """strip_think 去掉 <think> 块"""
        text = "<think>reasoning</think>\n{\"intents\":[\"weather\"]}"
        cleaned = self._clean_intent_response(text)
        assert cleaned == '{"intents":["weather"]}'

    def test_clean_json_fences(self):
        """去 ```json ... ``` fences"""
        text = "```json\n{\"intents\":[\"weather\"]}\n```"
        cleaned = self._clean_intent_response(text)
        assert cleaned == '{"intents":["weather"]}'

    def test_clean_think_and_fences(self):
        """同时去 think + fences"""
        text = "<think>reasoning</think>```json\n{\"intents\":[\"weather\"]}\n```"
        cleaned = self._clean_intent_response(text)
        assert cleaned == '{"intents":["weather"]}'

    def test_extract_json_from_mess(self):
        """从混杂文本中抽取 JSON"""
        text = "好的,识别结果如下:{\"intents\":[\"weather\"],\"user_queries\":{},\"follow_up_message\":\"\"}"
        cleaned = self._clean_intent_response(text)
        assert cleaned.startswith('{')
        assert '"intents":["weather"]' in cleaned

    def test_pure_json_unchanged(self):
        """纯 JSON 不变"""
        text = '{"intents":["weather"],"user_queries":{},"follow_up_message":""}'
        cleaned = self._clean_intent_response(text)
        assert cleaned == text

    def test_parse_valid_intent_json(self):
        """解析合法 intent JSON"""
        import json
        text = '{"intents":["weather","flight"],"user_queries":{"weather":"北京天气"},"follow_up_message":""}'
        result = json.loads(self._clean_intent_response(text))
        assert result["intents"] == ["weather", "flight"]
        assert result["user_queries"] == {"weather": "北京天气"}
        assert result["follow_up_message"] == ""

    def test_parse_invalid_json_returns_fallback(self):
        """解析失败时的 fallback 行为"""
        # 模仿 chat.py:443-447
        import json
        text = "抱歉,我没能理解您的意思。"
        try:
            json.loads(self._clean_intent_response(text))
        except json.JSONDecodeError:
            # fallback 路径
            fallback = ([], {}, text.strip() or "抱歉,我没能理解您的意思,请换个说法试试。")
            assert fallback == ([], {}, "抱歉,我没能理解您的意思。")


class TestFollowupDetection:
    """追问检测双保险逻辑(从 agents/ticket.py:367-400 提取)。

    关键行为:
    - is_followup: [追问] 前缀 OR (not has_data AND 含追问关键词)
    - has_data: 含 ¥/￥/余票/车次/航班/场馆/演出 任一
    """

    @staticmethod
    def _detect_followup(output: str):
        """复制 ticket.py:367-400 的检测逻辑"""
        has_data = (
            "¥" in output or "￥" in output
            or "余票" in output
            or "车次" in output
            or "航班" in output
            or "场馆" in output
            or "演出" in output
        )
        is_followup = (
            output.strip().startswith("[追问]")
            or (not has_data and (
                "请提供" in output or "请告诉我" in output or "请问您" in output
                or "缺少" in output or "哪一天" in output or "哪个城市" in output
                or "哪个车次" in output or "哪个航班" in output
                or "哪种座位" in output or "哪种票档" in output
            ))
        )
        return is_followup, has_data

    def test_explicit_followup_marker(self):
        """[追问] 前缀强制为追问"""
        is_follow, _ = self._detect_followup("[追问] 请告诉我出发城市")
        assert is_follow is True

    def test_data_response_not_followup(self):
        """含 ¥/车次 等数据时不判为追问"""
        is_follow, has_data = self._detect_followup("G1 次列车,二等座 ¥553")
        assert is_follow is False
        assert has_data is True

    def test_polite_phrase_with_data_not_followup(self):
        """含数据的礼貌用语不误判为追问"""
        is_follow, _ = self._detect_followup("为您查到以下航班:CA1234 北京到上海 ¥800")
        assert is_follow is False

    def test_polite_phrase_without_data_is_followup(self):
        """无数据的礼貌用语判为追问"""
        # 注意:不能含车次/航班/¥ 等数据关键词
        is_follow, has_data = self._detect_followup("请告诉我您想查询哪种座位")
        assert is_follow is True
        assert has_data is False

    def test_unknown_phrase_not_followup(self):
        """无关键词的普通回复不判为追问"""
        is_follow, has_data = self._detect_followup("好的,我帮您查询。")
        assert is_follow is False
        assert has_data is False
