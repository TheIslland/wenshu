"""Paragraph transform tests: four ops, ±20% cap, evidence gaps, rejection."""

from __future__ import annotations

import json

import pytest

from wenshu.errors import LLMError, ValidationFailed
from wenshu.llm import FakeLLM
from wenshu.services import paragraphs

PARAGRAPH = (
    "首先，2008 年之后，平台经济的兴起标志着粉丝劳动的重要转向[1]。"
    "其次，这种转向深刻地体现了媒介环境与消费逻辑之间的复杂性。"
    "再次，粉丝的实践活动呈现出一种结构性的文化逻辑。"
    "综上所述，我们应当以整体性的视角对其进行深入的分析。"
)

EVIDENCE = "2016 年统计显示应援 12.3 亿元。"


def fake_transform(revised: str, **extra) -> FakeLLM:
    payload = {"revised": revised, "ops": [], "gaps": [], "warnings": []} | extra
    return FakeLLM({"TASK:PARAGRAPH": json.dumps(payload, ensure_ascii=False)})


def test_compress_accepts_within_budget():
    revised = PARAGRAPH.replace("首先，", "").replace("再次，", "")
    result = paragraphs.transform(PARAGRAPH, op="compress", llm=fake_transform(revised))
    assert result.revised == revised
    assert result.mode == "compress"
    assert result.diff
    assert result.warnings == []


def test_expand_can_use_evidence_numbers():
    revised = PARAGRAPH + EVIDENCE
    result = paragraphs.transform(
        PARAGRAPH,
        op="expand",
        llm=fake_transform(revised, anchors=["2008 年"], preserved=["[1]"]),
        evidence=[EVIDENCE],
    )
    assert result.revised == revised
    assert any(item.get("action") == "anchors" for item in result.ops)
    assert any(item.get("action") == "preserved" for item in result.ops)
    assert result.mode == "expand"


def test_expand_rejects_numbers_outside_evidence():
    revised = PARAGRAPH + EVIDENCE
    result = paragraphs.transform(PARAGRAPH, op="expand", llm=fake_transform(revised))
    assert result.revised == PARAGRAPH
    assert any("数字" in warning for warning in result.warnings)


def test_length_cap_is_twenty_percent_even_when_asked_for_more():
    revised = (
        PARAGRAPH
        + "这是额外增加的一句话，用来让字数明显超限，同时也是为了测试二十个百分点这个硬上限是否真的会拦住超长输出。"
    )
    result = paragraphs.transform(
        PARAGRAPH, op="expand", llm=fake_transform(revised), max_delta=0.5, evidence=[EVIDENCE]
    )
    assert result.revised == PARAGRAPH
    assert any("20%" in warning for warning in result.warnings)


def test_transform_rejects_removed_citation():
    revised = PARAGRAPH.replace("[1]", "")
    result = paragraphs.transform(PARAGRAPH, op="compress", llm=fake_transform(revised))
    assert result.revised == PARAGRAPH
    assert any("引用" in warning for warning in result.warnings)


def test_transform_second_scan_rejects_new_style_hits():
    revised = PARAGRAPH + "这不是偶然，而是必然。"
    result = paragraphs.transform(PARAGRAPH, op="argument", llm=fake_transform(revised))
    assert result.revised == PARAGRAPH
    assert any("引入了新的风格问题" in warning for warning in result.warnings)


def test_compress_without_llm_deletes_boilerplate():
    result = paragraphs.transform(PARAGRAPH, op="compress", llm=None)
    assert "首先" not in result.revised
    assert result.gaps
    assert any("没有配置 LLM" in warning for warning in result.warnings)
    assert result.mode == "compress"


@pytest.mark.parametrize("op", ["expand", "reorder", "argument"])
def test_other_ops_without_llm_leave_text_alone(op: str):
    result = paragraphs.transform(PARAGRAPH, op=op, llm=None)
    assert result.revised == PARAGRAPH
    assert result.warnings
    if op in {"expand", "argument"}:
        assert any("缺证据池" in gap for gap in result.gaps)


def test_missing_evidence_is_reported_as_gap():
    result = paragraphs.transform(PARAGRAPH, op="expand", llm=None, evidence=[])
    assert any("缺证据池" in gap for gap in result.gaps)
    assert any("扩写需要 LLM" in warning for warning in result.warnings)


def test_empty_llm_answer_falls_back_to_rules():
    result = paragraphs.transform(PARAGRAPH, op="compress", llm=fake_transform(""))
    assert result.revised
    assert any("没有返回调段结果" in warning for warning in result.warnings)


def test_unknown_op_and_role_are_rejected():
    with pytest.raises(ValidationFailed):
        paragraphs.transform(PARAGRAPH, op="rewrite", llm=None)
    with pytest.raises(ValidationFailed):
        paragraphs.transform(PARAGRAPH, op="compress", llm=None, role="unknown")


def test_empty_text_is_rejected():
    with pytest.raises(ValidationFailed):
        paragraphs.transform("  ", op="compress", llm=None)


def test_upstream_failure_raises_llm_error():
    class BoomLLM:
        provider = "boom"
        model = "boom"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        def chat_json(self, messages, schema, *, retries=1, max_tokens=2500):
            raise LLMError("模拟上游失败")

    with pytest.raises(LLMError):
        paragraphs.transform(PARAGRAPH, op="compress", llm=BoomLLM())
