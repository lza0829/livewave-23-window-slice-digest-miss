"""窗键切片摘要夹具：入窗摘要冻结（全局唯一设计取舍，不贯彻迁移工单重切片）。

钉死：
- 入窗归属与摘要同票：事件编号/窗型参数快照/窗键集合/摘要哈希四件齐，哈希可核；
- 核证只读接口：钉死=True、可现算重挂=False，只读不写；
- 入窗后改步长再撤回：撤回仍挂原摘要键，旧摘要不被回溯改挂；
- 负夹：摘要空 / 撤回挂摘要外 / 摘要与窗行键集分叉 → 贯验报警；
- 半截失败整票回滚：摘要写失败 → 整批事件/窗联/摘要/批次都不留；
- 改步长×入流抢锁：同一房不得两套窗键混关，摘要与窗联逐事件一致。
"""
import json
import os
import sqlite3
import threading

import pytest
from fastapi import HTTPException


def _库行(sql, 参=()):
    conn = sqlite3.connect(os.environ["数据目录"] + "/播浪.db")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, 参).fetchall()
    finally:
        conn.close()


def _库写(sql, 参=()):
    conn = sqlite3.connect(os.environ["数据目录"] + "/播浪.db")
    try:
        conn.execute(sql, 参)
        conn.commit()
    finally:
        conn.close()


def _事件(编号, 事件时, 赞=1, 房="房A"):
    return {
        "事件编号": 编号, "房间键": 房, "事件类型": "点赞",
        "事件时": 事件时, "处理时": 事件时, "观众键": "测", "点赞增量": 赞, "送礼额": 0,
    }


def _装(客户, 批次, 事件):
    r = 客户.post("/api/装载", json={"批次编号": 批次, "事件": 事件})
    assert r.status_code == 200, r.text
    return r.json()


def _摘要(事件编号):
    行 = _库行("SELECT * FROM 窗键切片摘要 WHERE 事件编号=?", (事件编号,))
    assert len(行) == 1, f"事件{事件编号}摘要应恰1行，实{len(行)}"
    return dict(行[0])


def test_入窗同票摘要_字段齐哈希可核(客户):
    from app.modules import 窗键切片摘要 as 切

    报 = 客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"}).json()
    assert 报["入窗"] == 3
    for 明 in 报["明细"]:
        assert 明["摘要哈希"], "入窗明细须带摘要哈希"
    for 编 in ("甲1", "甲2", "甲3"):
        d = _摘要(编)
        集 = json.loads(d["窗键集合"])
        参 = json.loads(d["窗型参数"])
        assert 集, "禁止入窗成功摘要空"
        assert 参 == {"窗型": "翻滚", "窗长秒": 60, "滑动步长秒": 60, "窗代": 1}
        assert d["摘要哈希"] == 切.计算哈希(编, 参, 集)
        assert d["批号"] == "批-翻滚-01" and d["时刻"]
        联 = _库行("SELECT 窗键 FROM 事件窗联 WHERE 事件编号=?", (编,))
        assert sorted(r["窗键"] for r in 联) == sorted(集)
        ev = _库行("SELECT 窗键 FROM 互动事件 WHERE 事件编号=?", (编,))[0]
        assert ev["窗键"] == 集[-1], "主窗键=摘要集合末位"
    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]


def test_核证只读接口_钉死不可重挂(客户):
    客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"})
    体 = 客户.get("/api/核证/窗键切片").json()
    assert 体["钉死"] is True and 体["可现算重挂"] is False
    assert 体["通过"] is True and len(体["切片"]) == 3
    assert 体["协同"]["窗参页"]["窗代"] == 1
    for s in 体["切片"]:
        assert s["核证"]["通过"], s
    单 = 客户.get("/api/核证/窗键切片", params={"事件编号": "甲1"}).json()
    assert len(单["切片"]) == 1 and 单["切片"][0]["事件编号"] == "甲1"
    前 = _库行("SELECT COUNT(*) c FROM 窗键切片摘要")[0]["c"]
    客户.get("/api/核证/窗键切片")
    客户.get("/api/核证/窗键切片", params={"事件编号": "甲2"})
    assert _库行("SELECT COUNT(*) c FROM 窗键切片摘要")[0]["c"] == 前, "核证接口只读不写"


def test_改步长再撤回_仍挂原摘要键(客户):
    """甲夹具：入窗 → 改步长 → 再撤回；撤回仍挂原摘要键，旧摘要不回溯改挂。"""
    # ① 入窗：g1 翻滚，准时样例关窗 + 迟到修正（L1 撤回挂 g1 摘要键）
    客户.post("/api/装载/夹具", params={"名": "准时热度样例"})
    客户.post("/api/装载/夹具", params={"名": "迟到修正样例"})
    d1 = _摘要("L1")
    集1 = json.loads(d1["窗键集合"])
    assert 集1 == ["房A|g1|2026-11-22T12:00:00Z"]
    撤1 = _库行("SELECT * FROM 撤回单 WHERE 事件编号='L1'")
    assert len(撤1) == 1 and 撤1[0]["窗键"] in 集1

    # ② 改步长：排水清场 → 换代 g2 滑动60/30
    客户.post("/api/排水", json={})
    r = 客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    assert r.status_code == 200 and r.json()["窗代"] == 2

    # ③ 再撤回：新代迟到修正，撤回挂新事件自身摘要内 g2 键
    _装(客户, "批-w1", [_事件("w1", "2026-11-22T12:10:10Z", 3)])
    _装(客户, "批-w2", [_事件("w2", "2026-11-22T12:10:55Z", 1)])
    报 = _装(客户, "批-w3", [_事件("w3", "2026-11-22T12:10:20Z", 2)])
    assert 报["明细"][0]["修正窗数"] == 1
    集3 = json.loads(_摘要("w3")["窗键集合"])
    撤3 = _库行("SELECT * FROM 撤回单 WHERE 事件编号='w3'")
    assert len(撤3) == 1 and 撤3[0]["窗键"] in 集3 and "|g2|" in 撤3[0]["窗键"]

    # ④ 冻结：旧摘要不被回溯改挂，旧撤回仍挂原摘要键
    d1b = _摘要("L1")
    assert d1b["摘要哈希"] == d1["摘要哈希"]
    assert json.loads(d1b["窗键集合"]) == 集1
    撤1b = _库行("SELECT * FROM 撤回单 WHERE 事件编号='L1'")
    assert 撤1b[0]["窗键"] in 集1 and "|g1|" in 撤1b[0]["窗键"]

    # ⑤ 摘要闸门：旧事件按新公式挂键须拒；无摘要事件一律拒
    from app.db import 连接
    from app.modules import 窗键切片摘要 as 切

    conn = 连接()
    try:
        assert 切.应拒摘要外挂(conn, "L1", "房A|g2|2026-11-22T12:00:00Z") is True
        assert 切.应拒摘要外挂(conn, "L1", 集1[0]) is False
        assert 切.应拒摘要外挂(conn, "查无此事件", 集1[0]) is True
    finally:
        conn.close()

    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]


def test_入窗成功摘要空_贯验报警(客户):
    客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"})
    _库写("DELETE FROM 窗键切片摘要 WHERE 事件编号='甲1'")
    验 = 客户.post("/api/贯验").json()
    assert not 验["是否通过"]
    assert any("摘要" in p and "甲1" in p for p in 验["问题"]), 验["问题"]


def test_撤回挂摘要外窗键_贯验报警(客户):
    客户.post("/api/装载/夹具", params={"名": "准时热度样例"})
    客户.post("/api/装载/夹具", params={"名": "迟到修正样例"})
    # 手改：撤回单挂到摘要外窗键（模拟按新公式改挂）
    _库写("UPDATE 撤回单 SET 窗键='房A|g9|2026-11-22T12:00:00Z' WHERE 事件编号='L1'")
    验 = 客户.post("/api/贯验").json()
    assert not 验["是否通过"]
    assert any("摘要外" in p for p in 验["问题"]), 验["问题"]


def test_摘要与窗行键集分叉_贯验报警(客户):
    客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"})
    _库写("DELETE FROM 事件窗联 WHERE 事件编号='甲1'")
    验 = 客户.post("/api/贯验").json()
    assert not 验["是否通过"]
    assert any("分叉" in p and "甲1" in p for p in 验["问题"]), 验["问题"]


def test_半截失败整票回滚(客户, monkeypatch):
    from app.modules import 窗键切片摘要 as 切

    真写 = 切.尝试写切片
    计数 = {"n": 0}

    def 坏写(conn, **kw):
        计数["n"] += 1
        if 计数["n"] == 2:
            raise RuntimeError("摘要写入失败（模拟半截）")
        return 真写(conn, **kw)

    monkeypatch.setattr(切, "尝试写切片", 坏写)
    with pytest.raises(RuntimeError):
        客户.post("/api/装载", json={
            "批次编号": "批-半截",
            "事件": [_事件("h1", "2026-11-22T12:00:05Z", 1), _事件("h2", "2026-11-22T12:00:10Z", 2)],
        })
    # 整票回滚：事件/窗联/摘要/批次/窗合计都不留半截
    assert not _库行("SELECT * FROM 互动事件 WHERE 批次编号='批-半截'")
    assert not _库行("SELECT * FROM 事件窗联 WHERE 事件编号 IN ('h1','h2')")
    assert not _库行("SELECT * FROM 窗键切片摘要 WHERE 批号='批-半截'")
    assert not _库行("SELECT * FROM 装载批次 WHERE 编号='批-半截'")
    窗 = _库行("SELECT * FROM 热度窗 WHERE 窗键='房A|g1|2026-11-22T12:00:00Z'")
    assert not 窗 or 窗[0]["事件笔数"] == 0
    # 回滚后主链无恙：好批照常入窗，贯验通过
    报 = _装(客户, "批-好", [_事件("h3", "2026-11-22T12:00:20Z", 5)])
    assert 报["入窗"] == 1 and _摘要("h3")
    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]


def test_并发_改步长入流_摘要与窗联不分叉(库):
    """再夹：改步长与入流抢锁——正式不得同一房两套窗键混关，摘要逐事件一致。"""
    from app.services import 装载, 窗参, 贯验

    窗参.改窗参("滑动", 60, 30)
    装载.装一批({"批次编号": "批-d0", "事件": [_事件("d0", "2026-11-22T12:00:05Z", 1)]})

    错 = []

    def 入流(i):
        try:
            装载.装一批({
                "批次编号": f"批-d{i}",
                "事件": [_事件(f"d{i}a", f"2026-11-22T12:0{1+i}:10Z", 1),
                         _事件(f"d{i}b", f"2026-11-22T12:0{1+i}:40Z", 2)],
            })
        except HTTPException as e:
            错.append(("入流", e.status_code))

    def 改参(i):
        try:
            窗参.改窗参("滑动", 60, 20)
        except HTTPException as e:
            if e.status_code != 409:
                错.append(("改参", e.status_code))

    线程 = []
    for i in range(1, 4):
        线程 += [threading.Thread(target=入流, args=(i,)), threading.Thread(target=改参, args=(i,))]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join()
    assert not 错, 错

    assert not _库行(
        "SELECT 房间键, COUNT(DISTINCT 窗代) c FROM 热度窗 WHERE 状态='开启' GROUP BY 房间键 HAVING c>1"
    )
    for r in _库行("SELECT 事件编号 FROM 互动事件 WHERE 命运='已入窗'"):
        d = _库行("SELECT 窗键集合 FROM 窗键切片摘要 WHERE 事件编号=?", (r["事件编号"],))
        assert len(d) == 1, f"事件{r['事件编号']}摘要缺失"
        联 = _库行("SELECT 窗键 FROM 事件窗联 WHERE 事件编号=?", (r["事件编号"],))
        assert sorted(x["窗键"] for x in 联) == sorted(json.loads(d[0]["窗键集合"]))
    验 = 贯验.跑贯验()
    assert 验["是否通过"], 验["问题"]
