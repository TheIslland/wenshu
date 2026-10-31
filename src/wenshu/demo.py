"""Fictional demo data for `wenshu --demo` and screenshots.

All references below are synthetic and labelled as such. They are not real
publications; the demo must never be mistaken for a citable library.
"""

from __future__ import annotations

import json

from .db import Database
from .models import now_iso

DEMO_PROJECT = {
    "name": "县城屏幕：短视频里的地方感",
    "field": "传播学 / 文化研究",
    "question": "县城青年如何用短视频重写「地方」的意义？",
    "description": "演示项目：用一个虚构的县域短视频田野，串起检索、文献库、体检、润色、调段、方法矩阵、方向与流程。",
}

DEMO_REFS = [
    {
        "title": "县城的屏幕：短视频中的地方感生产（示例文献）",
        "authors": ["示例作者甲", "示例作者乙"],
        "year": 2024,
        "venue": "示例传播研究",
        "type": "journal-article",
        "language": "zh",
        "abstract": "本文以鲁中某县的 18 位青年创作者为样本，用深度访谈与内容分析讨论短视频如何把县城重新叙述为可被观看的地方。研究发现，创作者通过地标、方言与日常路线建立可识别性。",
        "tags": ["地方感", "短视频", "县域"],
        "note": "方法：深度访谈 + 内容分析；样本 18 人；局限：单县。",
        "status": "read",
    },
    {
        "title": "Platformed locality: short video and the remaking of place（示例文献）",
        "authors": ["Example, A.", "Example, B."],
        "year": 2023,
        "venue": "Journal of Example Media",
        "type": "journal-article",
        "language": "en",
        "abstract": "A comparative study of short-video platforms in three second-tier cities. Uses walkthrough method and 40 semi-structured interviews to argue that locality becomes a platform genre.",
        "tags": ["platform", "locality"],
        "note": "方法：walkthrough + 40 访谈；理论：platform studies。",
        "status": "read",
    },
    {
        "title": "「附近」的重建：数字媒介与日常生活（示例文献）",
        "authors": ["示例作者丙"],
        "year": 2022,
        "venue": "示例社会学刊",
        "type": "journal-article",
        "language": "zh",
        "abstract": "从「附近的消失」出发，讨论数字媒介如何同时削弱与重建地方感。采用民族志方法，在三个社区进行为期一年的观察。",
        "tags": ["附近", "民族志"],
        "note": "方法：民族志；概念：附近。",
        "status": "reading",
    },
    {
        "title": "短视频平台的算法可见性（示例文献）",
        "authors": ["示例作者丁"],
        "year": 2025,
        "venue": "示例新闻与传播研究",
        "type": "journal-article",
        "language": "zh",
        "abstract": "基于 12 个账号的流量数据与创作者访谈，讨论算法可见性如何塑造县域创作者的内容选择，并提出「可被推荐的本地性」概念。",
        "tags": ["算法", "可见性"],
        "note": "方法：混合方法（账号数据 + 访谈）；概念：可被推荐的本地性。",
        "status": "inbox",
        "doi": None,
    },
    {
        "title": "Doing qualitative research in a digital age（示例文献）",
        "authors": ["Example, C."],
        "year": 2021,
        "venue": "Example Press",
        "type": "book",
        "language": "en",
        "abstract": "A methods handbook covering interviews, digital ethnography and content analysis, with attention to researcher positionality.",
        "tags": ["方法", "质性研究"],
        "note": "方法手册；用于方法章。",
        "status": "read",
    },
    {
        "title": "The presentation of self in everyday life（示例条目）",
        "authors": ["Example, D."],
        "year": 1959,
        "venue": "Example Books",
        "type": "book",
        "language": "en",
        "abstract": "拟剧论经典。演示用条目，元数据非真实版本，请勿引用。",
        "tags": ["理论", "自我呈现"],
        "note": "理论：拟剧论。",
        "status": "cited",
    },
]

DEMO_DOC = """# 摘要

随着短视频平台的不断发展，县域青年的地方感日益成为一个值得关注的重要议题。首先，短视频为地方提供了新的可见性；其次，它也重塑了青年与县城的关系；最后，这种关系反过来影响了内容生产。综上所述，本研究具有重要的理论意义与现实意义。

# 一、导论

2023 年至 2025 年，鲁中 A 县的短视频创作者从不足百人增长到三千余人。他们在镜头里反复拍摄同一条老街、同一家早餐铺、同一段方言。[@ref-1]

既有研究多把地方感当作短视频的「背景」，较少追问平台机制如何参与地方感的生成。本文认为，地方感不是被记录的对象，而是在拍摄、剪辑、发布与推荐中被一次次做出来的。

# 二、文献综述

平台研究提供了「可被推荐的本地性」这一线索。[@ref-4] 但该研究只分析了账号数据，没有进入创作者的日常路线；民族志研究则相反，它看见了路线，却较少处理算法。[@ref-3]

# 三、方法

本文采用深度访谈与内容分析相结合的混合方法，访谈 18 位创作者，并对其 240 条视频做编码。[@ref-1] 同时参考质性研究方法手册处理研究者位置与伦理问题。[@ref-5]

# 四、分析

创作者把「老街」当作可识别的符号：它既是地标，也是可被剪进 15 秒的叙事单位。值得注意的是，这种符号化并不是对地方的背叛，而是地方在平台上获得可读性的条件。

# 五、结论

本文回答开头的问题：县城青年通过选择可被推荐的符号，把地方重写为一种可流通的影像。研究局限在于单县样本，后续可做跨县比较。
"""

DEMO_TASKS = [
    ("选题", "把研究问题缩到「平台机制 × 地方感」", "done"),
    ("综述", "补三篇平台研究与两篇地方感中文文献", "doing"),
    ("综述", "做一张「方法—样本—结论」对照表", "todo"),
    ("写作", "重写导论第一段，删掉「随着…不断发展」", "todo"),
    ("核引", "逐条核 DOI，导出前跑一遍门禁", "todo"),
]


def seed_demo(db: Database) -> bool:
    con = db.connect()
    try:
        if con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]:
            return False
        now = now_iso()
        cur = con.execute(
            "INSERT INTO projects(name, field, question, description, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                DEMO_PROJECT["name"],
                DEMO_PROJECT["field"],
                DEMO_PROJECT["question"],
                DEMO_PROJECT["description"],
                "active",
                now,
                now,
            ),
        )
        project_id = int(cur.lastrowid or 0)
        cur = con.execute(
            "INSERT INTO documents(project_id, title, kind, content_md, word_count, version, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (project_id, "论文初稿", "paper", DEMO_DOC, len(DEMO_DOC), 1, now, now),
        )
        document_id = int(cur.lastrowid or 0)
        con.execute(
            "INSERT INTO snapshots(document_id, content_md, reason, created_at) VALUES(?,?,?,?)",
            (document_id, DEMO_DOC, "演示初始稿", now),
        )

        ref_ids: list[int] = []
        for index, ref in enumerate(DEMO_REFS, start=1):
            cur = con.execute(
                "INSERT INTO refs(title, authors, year, venue, type, language, abstract, source, "
                "source_id, bibkey, tags, note, status, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ref["title"],
                    json.dumps(ref["authors"], ensure_ascii=False),
                    ref["year"],
                    ref["venue"],
                    ref["type"],
                    ref["language"],
                    ref["abstract"],
                    "demo",
                    f"demo-{index}",
                    f"demo{index}",
                    json.dumps(ref["tags"], ensure_ascii=False),
                    ref["note"],
                    ref["status"],
                    now,
                    now,
                ),
            )
            ref_id = int(cur.lastrowid or 0)
            ref_ids.append(ref_id)
            con.execute(
                "INSERT INTO project_refs(project_id, ref_id, relevance, added_at) VALUES(?,?,?,?)",
                (project_id, ref_id, 1.0, now),
            )

        methods = [
            ("深度访谈 + 内容分析", "18 位创作者、240 条视频", "鲁中 A 县", "地方感", "符号化是地方获得可读性的条件", "单县、无平台后台数据", ref_ids[0]),
            ("Walkthrough + 访谈", "三个二线城市、40 人", "平台比较", "平台研究", "本地性成为平台类型", "以城市为主，缺县域", ref_ids[1]),
            ("民族志", "三个社区、一年", "社区日常", "附近", "数字媒介同时削弱与重建地方感", "未处理算法", ref_ids[2]),
        ]
        for method in methods:
            con.execute(
                "INSERT INTO method_rows(project_id, ref_id, method, data, sample, theory, finding, "
                "limitation, evidence, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project_id, method[6], *method[:6], json.dumps(["（演示证据句）"], ensure_ascii=False), now),
            )

        for index, (stage, title, status) in enumerate(DEMO_TASKS):
            con.execute(
                "INSERT INTO tasks(project_id, stage, title, status, due, notes, sort, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (project_id, stage, title, status, None, "", index, now, now),
            )
        con.commit()
        return True
    finally:
        con.close()
