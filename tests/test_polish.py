"""Polish tests: ±15% budget, protected citations/terms, no-LLM fallback."""

from __future__ import annotations

import json

import pytest

from wenshu.errors import LLMError, ValidationFailed
from wenshu.llm import FakeLLM
from wenshu.services import polish

HUMAN_SAMPLE = (
    "1926 年，鲁迅在《藤野先生》里写下“幻灯片事件”，说自己从此弃医从文。"
    "这个说法后来被反复引用[1]。不过，周作人在 1960 年代回忆时给出了另一个版本："
    "留日学生看幻灯片的场合并不稀奇。两处叙述的裂缝，恰好说明“弃医从文”更像一次事后的自我叙述。"
    "短句。这句稍微长一些，用来把叙述版本之间那点不好解释的缝隙摊开来看，"
    "交代材料从哪里来、到哪里为止。"
)

TERM_SAMPLE = "周作人在 1960 年代回忆时给出了另一个版本，并讨论了幻灯片事件的场合。"


def fake_polish(revised: str, **extra) -> FakeLLM:
    payload = {"revised": revised, "ops": [], "gaps": [], "warnings": []} | extra
    return FakeLLM({"TASK:POLISH": json.dumps(payload, ensure_ascii=False)})


def test_polish_accepts_safe_rewrite():
    revised = HUMAN_SAMPLE.replace("短句。", "这是一个很短的句子。")
    result = polish.polish(HUMAN_SAMPLE, mode="concise", llm=fake_polish(revised))
    assert result.revised == revised
    assert result.mode == "concise"
    assert result.diff
    assert result.warnings == []
    assert result.provider == "fake"


def test_polish_rejects_length_budget_breach():
    revised = (
        HUMAN_SAMPLE
        + "这是额外补充的一句，用来把字数推高一点点，也顺便测试十五个百分点这条线。"
    )
    result = polish.polish(HUMAN_SAMPLE, mode="academic", llm=fake_polish(revised))
    assert result.revised == HUMAN_SAMPLE
    assert any("字数变动" in warning for warning in result.warnings)
    assert result.ops[0]["action"] == "rejected"


def test_polish_rejects_removed_citation():
    revised = HUMAN_SAMPLE.replace("[1]", "")
    result = polish.polish(HUMAN_SAMPLE, mode="concise", llm=fake_polish(revised))
    assert result.revised == HUMAN_SAMPLE
    assert any("引用" in warning for warning in result.warnings)


def test_polish_rejects_changed_quotation():
    revised = HUMAN_SAMPLE.replace("幻灯片事件", "幻灯片事件（修订）")
    result = polish.polish(HUMAN_SAMPLE, mode="academic", llm=fake_polish(revised))
    assert result.revised == HUMAN_SAMPLE
    assert any("引文" in warning for warning in result.warnings)


def test_polish_rejects_replaced_term():
    revised = TERM_SAMPLE.replace("周作人", "鲁迅")
    result = polish.polish(TERM_SAMPLE, mode="concise", llm=fake_polish(revised), terms=["周作人"])
    assert result.revised == TERM_SAMPLE
    assert any("术语" in warning for warning in result.warnings)


def test_polish_rejects_new_style_hits():
    revised = HUMAN_SAMPLE + "首先，综上所述，这深刻地体现了时代。"
    result = polish.polish(HUMAN_SAMPLE, mode="academic", llm=fake_polish(revised))
    assert result.revised == HUMAN_SAMPLE
    assert any("引入了新的风格问题" in warning for warning in result.warnings)


def test_polish_without_llm_still_answers_in_plain_chinese():
    text = "首先，我们对材料进行了分析。其次，这个结论成立。"
    result = polish.polish(text, mode="academic", llm=None)
    assert "首先" not in result.revised
    assert result.mode == "academic"
    assert result.warnings
    assert "润色需要 LLM" in result.warnings[0]


def test_polish_unknown_mode_is_rejected():
    with pytest.raises(ValidationFailed):
        polish.polish("一段文字。", mode="vibes", llm=None)


def test_polish_empty_text_is_rejected():
    with pytest.raises(ValidationFailed):
        polish.polish("   ", mode="academic", llm=None)


def test_polish_upstream_failure_raises_llm_error():
    class BoomLLM:
        provider = "boom"
        model = "boom"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        def chat_json(self, messages, schema, *, retries=1, max_tokens=2500):
            raise LLMError("模拟上游失败")

    with pytest.raises(LLMError):
        polish.polish(HUMAN_SAMPLE, mode="academic", llm=BoomLLM())


def test_rewrite_service_rejects_new_citation():
    from wenshu.services import rewrite

    revised = HUMAN_SAMPLE.replace("被反复引用[1]", "被反复引用[1][@newkey]")
    llm = FakeLLM(
        {
            "TASK:STYLE_REWRITE": json.dumps(
                {"revised": revised, "ops": [], "gaps": [], "warnings": []},
                ensure_ascii=False,
            )
        }
    )
    result = rewrite.rewrite(HUMAN_SAMPLE, mode="academic", llm=llm)
    assert result.revised == HUMAN_SAMPLE
    assert any("引用" in warning for warning in result.warnings)


def test_polish_works_without_passing_llm():
    result = polish.polish("首先，我们对材料进行了分析。其次，这个结论成立。")
    assert result.revised
    assert result.warnings
