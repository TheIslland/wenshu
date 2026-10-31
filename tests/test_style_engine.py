"""Engine tests: risk scoring, baseline z-scores, LLM review, safe fixes."""

from __future__ import annotations

import json
import time

import pytest

from wenshu.errors import LLMError, ValidationFailed
from wenshu.llm import FakeLLM
from wenshu.models import StyleFinding
from wenshu.services.style import baseline, engine, metrics, rules

AI_SAMPLE = (
    "首先，值得注意的是，在当代文化研究的语境中，偶像文化的兴起标志着青年亚文化的重要转向。"
    "其次，这种转向深刻地体现了媒介环境与消费逻辑之间的复杂性、多元性和互动性。"
    "再次，粉丝的实践活动呈现出一种结构性的、整体性的文化逻辑。"
    "最后，这种逻辑在平台资本与情感劳动的互动中获得了新的形态。"
    "综上所述，上述分析表明，所谓的“情感劳动”与“平台资本”已经构成一种新的“文化机制”，"
    "这一机制不是审美问题，而是社会结构问题——由此可见，我们应当以整体性的视角对其深入分析，"
    "作出更加系统化的回应。这种以平台资本、情感劳动与粉丝实践为基础的文化机制，"
    "在当代青年亚文化的日常经验与媒介消费的各个环节之中，呈现出一种可以被识别出来的、"
    "具有结构性的整体逻辑。"
)

HUMAN_SAMPLE = (
    "1926 年，鲁迅在《藤野先生》里写下“幻灯片事件”，说自己从此弃医从文。"
    "这个说法后来被反复引用[1]。不过，周作人在 1960 年代回忆时给出了另一个版本："
    "留日学生看幻灯片的场合并不稀奇。两处叙述的裂缝，恰好说明“弃医从文”更像一次事后的自我叙述。"
    "短句。这句稍微长一些，用来把叙述版本之间那点不好解释的缝隙摊开来看，"
    "交代材料从哪里来、到哪里为止。"
)


def test_analyze_separates_ai_style_from_human_style():
    ai_report = engine.analyze(AI_SAMPLE)
    human_report = engine.analyze(HUMAN_SAMPLE)
    assert ai_report.score >= 60
    assert ai_report.level == "high"
    assert human_report.score <= 15
    assert human_report.level == "low"
    assert ai_report.score > human_report.score


def test_report_never_claims_ai_probability():
    payload = json.dumps(engine.analyze(AI_SAMPLE).model_dump(), ensure_ascii=False)
    assert "AI 概率" not in payload
    assert "ai_probability" not in payload
    assert "AIGC" not in payload
    assert "风格风险" in engine.analyze(AI_SAMPLE).summary


def test_report_shape_and_metric_types():
    report = engine.analyze(AI_SAMPLE)
    assert report.metrics
    assert all(isinstance(value, float) for value in report.metrics.values())
    assert report.findings
    assert report.baseline_used is False
    assert "默认冷启动阈值" in report.summary


def test_empty_text_returns_clean_report():
    report = engine.analyze("")
    assert report.score == 0.0
    assert report.level == "low"
    assert report.findings == []
    assert "为空" in report.summary


def test_very_long_paragraph_does_not_blow_up():
    text = ("首先，这是一个用于压力测试的句子。其次，我们看材料——这不是偶然，而是必然。" * 500)[
        :20000
    ]
    report = engine.analyze(text)
    assert 0 <= report.score <= 100
    fixed = engine.apply_safe_fixes(text, report.findings)
    assert isinstance(fixed["revised"], str)
    assert any(op["op"] in {"equal", "insert", "delete"} for op in fixed["diff"])


def test_baseline_builds_mean_and_std():
    data = baseline.build([HUMAN_SAMPLE, HUMAN_SAMPLE, HUMAN_SAMPLE])
    assert data["samples"] == 3
    assert data["metrics"]["sentence_cv"]["mean"] > 0
    assert data["metrics"]["sentence_cv"]["std"] >= 0
    assert data["warnings"] == []


def test_baseline_needs_at_least_one_text():
    with pytest.raises(ValidationFailed):
        baseline.build([])


def test_baseline_discounts_author_habits():
    habit = "首先，我们看材料。其次，我们看机制。综上所述，我们应当继续讨论。"
    data = baseline.build([habit, habit, habit])
    without = engine.analyze(habit)
    with_baseline = engine.analyze(habit, baseline=data)
    assert with_baseline.baseline_used is True
    assert with_baseline.score <= without.score
    assert any("基线" in warning for warning in with_baseline.warnings)


def test_baseline_score_reports_deviations_against_other_style():
    data = baseline.build([AI_SAMPLE, AI_SAMPLE, AI_SAMPLE])
    result = baseline.score(metrics.compute(HUMAN_SAMPLE), data)
    assert result["applied"] is True
    assert result["deviations"]
    assert {item["metric"] for item in result["deviations"]}


def test_llm_review_adds_semantic_findings_with_evidence_span():
    quote = "所谓的“情感劳动”与“平台资本”已经构成一种新的“文化机制”"
    llm = FakeLLM(
        {
            "TASK:STYLE_REVIEW": json.dumps(
                {
                    "findings": [
                        {
                            "rule_id": "argument_jump",
                            "quote": quote,
                            "message": "断言了机制的存在，但没有给出机制如何运作的材料。",
                            "suggestion": "补一条平台规则或访谈材料，或把这句降级为假设。",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        }
    )
    report = engine.analyze(AI_SAMPLE, llm=llm)
    assert report.llm_used is True
    semantic = [f for f in report.findings if f.rule_id == "argument_jump"]
    assert len(semantic) == 1
    assert semantic[0].text == quote
    assert AI_SAMPLE[semantic[0].start : semantic[0].end] == quote
    assert semantic[0].weight > 0


def test_llm_review_drops_unlocatable_evidence():
    llm = FakeLLM(
        {
            "TASK:STYLE_REVIEW": json.dumps(
                {
                    "findings": [
                        {
                            "rule_id": "concession_gap",
                            "quote": "这句话根本不在原文里",
                            "message": "没有让步。",
                            "suggestion": "补反例。",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        }
    )
    report = engine.analyze(AI_SAMPLE, llm=llm)
    assert not [f for f in report.findings if f.rule_id == "concession_gap"]
    assert any("定位" in warning for warning in report.warnings)


def test_llm_failure_degrades_to_rules():
    class BoomLLM:
        provider = "boom"
        model = "boom"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        def chat_json(self, messages, schema, *, retries=1, max_tokens=2500):
            raise LLMError("模拟上游失败")

    report = engine.analyze(AI_SAMPLE, llm=BoomLLM())
    assert report.llm_used is False
    assert any("语义复审失败" in warning for warning in report.warnings)
    assert report.findings  # offline rules still ran


def test_safe_fixes_only_touch_boilerplate_verbs_and_dashes():
    text = "首先，2020 年的研究进行了分析——这一点很关键。其次，这个结论成立。"
    report = engine.analyze(text)
    fixed = engine.apply_safe_fixes(text, report.findings)
    assert "首先" not in fixed["revised"]
    assert "2020" in fixed["revised"]
    assert "——" not in fixed["revised"]
    assert fixed["applied"]
    assert {item["rule_id"] for item in fixed["applied"]} <= rules.AUTO_FIXABLE_RULES
    rebuilt = "".join(
        op["text"] for op in fixed["diff"] if op["op"] in {"equal", "insert"}
    )
    assert rebuilt == fixed["revised"]


def test_safe_fixes_skip_non_fixable_findings():
    finding = StyleFinding(
        rule_id="concreteness_gap",
        name="具体性缺失",
        start=0,
        end=2,
        text="材料",
        auto_fixable=False,
    )
    result = engine.apply_safe_fixes("材料", [finding])
    assert result["revised"] == "材料"
    assert result["applied"] == []
    assert result["warnings"]


def test_safe_fixes_tolerate_stale_spans():
    stale = StyleFinding(
        rule_id="boilerplate",
        name="总分总套话",
        start=999,
        end=1001,
        text="首先",
        auto_fixable=True,
    )
    result = engine.apply_safe_fixes("很短的一段。", [stale])
    assert result["revised"] == "很短的一段。"
    assert result["warnings"]


def test_safe_fixes_keep_citations_and_quoted_text():
    text = "首先，“引文原文”被反复引用[2]。其次，见 2021 年的数据。"
    fixed = engine.apply_safe_fixes(text, engine.analyze(text).findings)
    assert "首先" not in fixed["revised"]
    assert "“引文原文”" in fixed["revised"]
    assert "[2]" in fixed["revised"]
    assert "2021" in fixed["revised"]


def test_char_diff_round_trips():
    original = "这是一段话。"
    revised = "这是一段新的话。"
    ops = engine.char_diff(original, revised)
    assert "".join(op["text"] for op in ops if op["op"] != "insert") == original
    assert "".join(op["text"] for op in ops if op["op"] != "delete") == revised


def test_second_scan_helper_detects_introduced_hits():
    new = HUMAN_SAMPLE + "首先，综上所述，这一现象深刻地体现了时代精神。"
    assert "boilerplate" in engine.introduced_rule_ids(HUMAN_SAMPLE, new)
    assert engine.introduced_rule_ids(HUMAN_SAMPLE, HUMAN_SAMPLE) == []


def test_check_preserved_rejects_new_citations_and_quotes():
    original = "鲁迅在 1926 年写了这篇文章[1]。"
    assert engine.check_preserved(original, original) == []
    assert engine.check_preserved(original, "鲁迅在 1926 年写了这篇文章[1][@new]。")
    revised = "鲁迅在 1926 年写了这篇文章[1]，见《新书名》。"
    assert engine.check_preserved(original, revised)
    assert engine.check_preserved(original, revised, allowed_extra="《新书名》") == []


def test_apply_safe_fixes_accepts_dict_findings():
    text = "首先，我们看材料。其次，我们看机制。"
    findings = [
        finding.model_dump()
        for finding in engine.analyze(text).findings
        if finding.rule_id == "boilerplate"
    ]
    fixed = engine.apply_safe_fixes(text, findings)
    assert "首先" not in fixed["revised"]
    assert fixed["applied"]


def test_llm_call_retries_once_after_transport_failure():
    class FlakyLLM:
        provider = "flaky"
        model = "flaky"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        def __init__(self):
            self.calls = 0

        def chat_json(self, messages, schema, *, retries=1, max_tokens=2500):
            self.calls += 1
            if self.calls == 1:
                raise LLMError("第一次失败")
            return schema()

    llm = FlakyLLM()
    output = engine.call_json_with_retry(
        llm, [{"role": "user", "content": "x"}], engine.LLMReview
    )
    assert isinstance(output, engine.LLMReview)
    assert llm.calls == 2


def test_call_json_with_timeout_reports_timeout():
    class SlowLLM:
        provider = "slow"
        model = "slow"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        def chat_json(self, messages, schema, *, retries=1, max_tokens=2500):
            time.sleep(0.3)
            return schema()

    with pytest.raises(LLMError):
        engine.call_json_with_timeout(
            SlowLLM(), [{"role": "user", "content": "x"}], engine.LLMReview, timeout_s=0.05
        )
