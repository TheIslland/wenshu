"""Rule coverage: every one of the 16 design rules has a golden sample."""

from __future__ import annotations

import pytest

from wenshu.services.style import engine, rules

SAMPLES: dict[str, str] = {
    "sentence_variance": (
        "这是第一句话，用来测试句长的变异。这是第二句话，用来测试长短的节奏。"
        "这是第三句话，用来测试读起来的呼吸。这是第四句话，用来测试句长的变化。"
    ),
    "same_length_run": (
        "第一句写十个字。第二句要写十四字左右啦。第三句十一个字。第四句十三个字的句子。"
        "这一句突然变得非常长，用来打破前面的匀速节奏但也让句长变异看起来足够大，只命中连续同长句。"
    ),
    "paragraph_evenness": "\n\n".join(
        ["这一段用来测试段落长度是否过于均匀，每段都写得差不多长。"] * 5
    ),
    "connective_density": "首先，我们需要材料。其次，我们需要机制。此外，我们还需要解释。",
    "connective_diversity": "因此，这一结论成立。" * 6,
    "four_char_runs": "我们要坚持统筹兼顾、标本兼治、宽严相济。",
    "boilerplate": "首先，我们看材料。其次，我们看机制。",
    "meaning_inflation": "这一转向标志着新的阶段，也体现了结构的变化。",
    "pseudo_depth": "这不是审美问题，而是结构问题。",
    "dash_quotes": "这是一个例子——用来测试破折号。",
    "vague_verb": "我们对材料进行了深入的分析。",
    "concreteness_gap": (
        "这一段讨论了文化的意义与结构，也谈到了媒介的作用与粉丝的实践，还说了平台与资本的关系"
        "以及情感劳动的位置，并且反复回到日常经验与制度安排之间的距离，但没有给出任何年份、"
        "数字、书名或引用标记。"
    ),
    "de_chain": "这是他所说的那个时代的文化研究的重要的历史的文本。",
}


def test_sixteen_rules_declared():
    assert len(rules.RULE_META) == 16
    assert len(rules.LLM_RULE_IDS) == 3
    offline = set(rules.RULE_META) - set(rules.LLM_RULE_IDS)
    assert len(offline) == 13


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_offline_rule_has_golden_sample(rule_id: str):
    findings = rules.detect(SAMPLES[rule_id])
    assert rule_id in {finding.rule_id for finding in findings}


def test_llm_only_rules_are_not_faked_without_llm():
    report = engine.analyze(SAMPLES["meaning_inflation"])
    assert not ({finding.rule_id for finding in report.findings} & set(rules.LLM_RULE_IDS))
    assert any("未接入 LLM" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    "text",
    [SAMPLES["sentence_variance"], SAMPLES["de_chain"], SAMPLES["meaning_inflation"]],
)
def test_every_finding_has_an_exact_span(text: str):
    for finding in rules.detect(text):
        assert 0 <= finding.start < finding.end <= len(text)
        assert text[finding.start : finding.end] == finding.text
        assert finding.message
        assert finding.suggestion


def test_boilerplate_needs_at_least_two_hits():
    assert "boilerplate" not in rules.rule_ids("首先，我们看材料，然后再看机制。")
    assert "boilerplate" in rules.rule_ids("首先，我们看材料。其次，我们看机制。")


def test_short_paragraphs_are_not_judged_for_variance():
    assert "sentence_variance" not in rules.rule_ids("短。很短。也短。")


def test_concreteness_gap_never_generates_text():
    findings = [f for f in rules.detect(SAMPLES["concreteness_gap"]) if f.rule_id == "concreteness_gap"]
    assert findings
    for finding in findings:
        assert finding.auto_fixable is False
        assert "待补" in finding.suggestion


def test_rule_findings_stay_bounded_on_huge_input():
    text = ("首先，我们看材料。其次，我们看机制。综上所述，由此可见——这不是偶然，而是必然。" * 600)[
        :20000
    ]
    findings = rules.detect(text)
    assert findings
    per_rule: dict[str, int] = {}
    for finding in findings:
        per_rule[finding.rule_id] = per_rule.get(finding.rule_id, 0) + 1
    assert max(per_rule.values()) <= 12
    assert len(findings) <= 16 * 12


def test_weights_are_shared_across_findings_of_one_rule():
    findings = [f for f in rules.detect(SAMPLES["boilerplate"]) if f.rule_id == "boilerplate"]
    assert len(findings) == 2
    total = sum(finding.weight for finding in findings)
    assert 0 < total <= rules.RULE_META["boilerplate"]["weight"] * 1.0
    assert findings[0].weight == findings[1].weight
