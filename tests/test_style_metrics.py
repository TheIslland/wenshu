"""Unit tests for the character-counted style metrics."""

from __future__ import annotations

from wenshu.services.style import metrics

AI_SAMPLE = (
    "首先，值得注意的是，在当代文化研究的语境中，偶像文化的兴起标志着青年亚文化的重要转向。"
    "其次，这种转向深刻地体现了媒介环境与消费逻辑之间的复杂性、多元性和互动性。"
    "再次，粉丝的实践活动呈现出一种结构性的、整体性的文化逻辑。"
    "最后，这种逻辑在平台资本与情感劳动的互动中获得了新的形态。"
    "综上所述，上述分析表明，所谓的“情感劳动”与“平台资本”已经构成一种新的“文化机制”，"
    "这一机制不是审美问题，而是社会结构问题——由此可见，我们应当以整体性的视角对其深入分析，"
    "作出更加系统化的回应。"
)


def test_compute_returns_float_metrics():
    values = metrics.compute(AI_SAMPLE)
    assert values
    assert all(isinstance(key, str) for key in values)
    assert all(isinstance(value, float) for value in values.values())
    assert set(metrics.THRESHOLDS) <= set(values)


def test_empty_text_is_safe():
    values = metrics.compute("")
    assert values["chars"] == 0.0
    assert values["sentences"] == 0.0
    assert values["paragraphs"] == 0.0
    assert values["units"] == 1.0
    assert values["sentence_cv"] == 0.0


def test_pure_english_never_divides_by_zero():
    values = metrics.compute("Plain English prose with 2020 and 12.5% anchors.")
    assert values["chars"] == 0.0
    assert values["units"] > 0.0
    assert values["anchor_per_100"] > 0.0
    assert values["connective_per_k"] >= 0.0


def test_sentence_and_paragraph_counts():
    values = metrics.compute("第一句。第二句。\n\n第三句。")
    assert values["paragraphs"] == 2.0
    assert values["sentences"] == 3.0


def test_sentence_cv_detects_uniform_and_varied_rhythm():
    uniform = "这是第一句话，用来测试句长的变异。这是第二句话，用来测试长短的节奏。这是第三句话，用来测试读起来的呼吸。这是第四句话，用来测试句长的变化。"
    varied = "短。这一句稍微长一点，但不至于太长。这一句则要长得多，它把材料、时间和地点都塞进来，好让句子长度拉开距离。又短了。"
    assert metrics.compute(uniform)["sentence_cv"] < 0.38
    assert metrics.compute(varied)["sentence_cv"] > 0.5


def test_connective_density_and_ttr():
    same = "因此，这一结论成立。" * 6
    values = metrics.compute(same)
    assert values["connectives"] == 6.0
    assert values["connective_ttr"] < 0.55  # only one distinct connective
    assert values["connective_per_k"] > 20.0


def test_nominalization_skips_lexicalized_words():
    assert metrics.compute("文化研究与女性写作")["nominalization_per_k"] == 0.0
    assert metrics.compute("这种复杂性很强。")["nominalization_per_k"] > 0.0


def test_anchor_density_counts_material():
    values = metrics.compute("1926 年，《藤野先生》这个说法被反复引用[1]，1960 年代又出现了另一个版本。")
    assert values["anchor_per_100"] > 1.0
    assert metrics.compute("只有抽象讨论，没有任何可以核对的材料。")["anchor_per_100"] == 0.0


def test_same_length_run_counts_consecutive_sentences():
    text = "第一句写十个字。第二句要写十四字左右啦。第三句十一个字。第四句十三个字的句子。"
    assert metrics.compute(text)["same_len_run"] >= 4.0


def test_very_long_paragraph_is_fast_and_safe():
    text = ("首先，这是一个用于压力测试的句子。" * 2000)[:20000]
    values = metrics.compute(text)
    assert values["chars"] > 15000
    assert values["units"] == values["chars"] or values["units"] > 0


def test_thresholds_match_design_section_7():
    assert metrics.THRESHOLDS["sentence_cv"] == 0.38
    assert metrics.THRESHOLDS["paragraph_cv"] == 0.30
    assert metrics.THRESHOLDS["connective_per_k"] == 20.0
    assert metrics.THRESHOLDS["dash_per_k"] == 1.5
    assert metrics.THRESHOLDS["vague_verb_per_k"] == 4.0
    assert metrics.THRESHOLDS["de_chain"] == 4.0
