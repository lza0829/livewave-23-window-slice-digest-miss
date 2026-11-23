"""滑动窗切分夹具：固定事件时点 + 改步长×入流并发。

口径钉死：
- 翻滚（步长=窗长）：甲类事件恰落 1 窗；
- 滑动（步长<窗长）：乙类事件恰落 窗长/步长 窗，窗键集可查且与步长一致；
- 改窗参：有开启窗 → 失败闭；排水后 → 换代隔离；
- 并发：同一房不得同时按两套规则关窗，一批不得半截双套窗键。
"""
import sqlite3
import threading

import pytest
from fastapi import HTTPException


def _库行(客户, sql, 参=()):
    import os

    conn = sqlite3.connect(os.environ["数据目录"] + "/播浪.db")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, 参).fetchall()
    finally:
        conn.close()


def _装(客户, 批次, 事件):
    r = 客户.post("/api/装载", json={"批次编号": 批次, "事件": 事件})
    assert r.status_code == 200, r.text
    return r.json()


def _事件(编号, 事件时, 赞=1, 房="房A"):
    return {
        "事件编号": 编号, "房间键": 房, "事件类型": "点赞",
        "事件时": 事件时, "处理时": 事件时, "观众键": "测", "点赞增量": 赞, "送礼额": 0,
    }




def test_甲_翻滚恰落一窗(客户):
    参 = 客户.get("/api/窗型").json()
    assert 参["窗型"] == "翻滚" and 参["窗长秒"] == 60 and 参["滑动步长秒"] == 60
    assert 参["窗代"] == 1 and 参["每事件窗数"] == 1 and 参["valid"] is True

    集 = 客户.get("/api/窗键集", params={"事件时": "2026-11-22T12:00:10Z", "房间键": "房A"}).json()
    assert 集["窗数"] == 1
    assert 集["事件窗键集"] == ["房A|g1|2026-11-22T12:00:00Z"]
    assert 集["主窗键"] == "房A|g1|2026-11-22T12:00:00Z"

    报 = 客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"}).json()
    assert 报["入窗"] == 3 and 报["每事件窗数"] == 1

    事件 = {e["事件编号"]: e for e in 客户.get("/api/事件").json()}
    assert 事件["甲1"]["窗数"] == 1 and 事件["甲1"]["窗键"] == "房A|g1|2026-11-22T12:00:00Z"
    assert 事件["甲2"]["窗键"] == "房A|g1|2026-11-22T12:00:00Z"
    assert 事件["甲3"]["窗键"] == "房A|g1|2026-11-22T12:01:00Z"

    窗 = {w["窗键"]: w for w in 客户.get("/api/热度窗").json()}
    assert 窗["房A|g1|2026-11-22T12:00:00Z"]["状态"] == "已关闭"
    assert 窗["房A|g1|2026-11-22T12:00:00Z"]["点赞合计"] == 3
    assert 窗["房A|g1|2026-11-22T12:00:00Z"]["送礼合计"] == 50
    assert 窗["房A|g1|2026-11-22T12:00:00Z"]["窗型"] == "翻滚"

    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]




def test_乙_滑动窗键集可查且与步长一致(客户):
    r = 客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    assert r.status_code == 200 and r.json()["已变更"] and r.json()["窗代"] == 2

    参 = 客户.get("/api/窗型").json()
    assert 参["窗型"] == "滑动" and 参["滑动步长秒"] == 30
    assert 参["每事件窗数"] == 2 and 参["valid"] is True

    集 = 客户.get("/api/窗键集", params={"事件时": "2026-11-22T12:10:10Z", "房间键": "房A"}).json()
    assert 集["窗数"] == 2
    assert 集["事件窗键集"] == ["房A|g2|2026-11-22T12:09:30Z", "房A|g2|2026-11-22T12:10:00Z"]
    assert 集["主窗键"] == "房A|g2|2026-11-22T12:10:00Z"

    报 = 客户.post("/api/装载/夹具", params={"名": "滑动窗样例"}).json()
    assert 报["入窗"] == 4 and 报["窗代"] == 2 and 报["每事件窗数"] == 2

    
    联 = _库行(客户, "SELECT 窗键 FROM 事件窗联 WHERE 事件编号=? ORDER BY 窗键", ("乙1",))
    assert [r["窗键"] for r in 联] == sorted(集["事件窗键集"])

    事件 = {e["事件编号"]: e for e in 客户.get("/api/事件").json()}
    assert 事件["乙1"]["窗数"] == 2 and 事件["乙1"]["窗键"] == "房A|g2|2026-11-22T12:10:00Z"
    assert 事件["乙4"]["窗数"] == 2

    窗 = {w["窗键"]: w for w in 客户.get("/api/热度窗").json()}
    
    assert 窗["房A|g2|2026-11-22T12:09:30Z"]["状态"] == "已关闭"
    assert 窗["房A|g2|2026-11-22T12:09:30Z"]["点赞合计"] == 5
    assert 窗["房A|g2|2026-11-22T12:09:30Z"]["送礼合计"] == 20
    assert 窗["房A|g2|2026-11-22T12:10:00Z"]["点赞合计"] == 7  
    assert 窗["房A|g2|2026-11-22T12:10:00Z"]["事件笔数"] == 3
    assert 窗["房A|g2|2026-11-22T12:10:30Z"]["状态"] == "开启"  
    assert 窗["房A|g2|2026-11-22T12:10:30Z"]["点赞合计"] == 3  

    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]




def test_开窗改参失败闭_排水后换代隔离(客户):
    客户.post("/api/装载/夹具", params={"名": "翻滚单窗样例"})
    
    r = 客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    assert r.status_code == 409
    体 = r.json()["detail"]
    assert 体["失败闭"] and any(x["房间键"] == "房A" for x in 体["未了开启窗"])
    
    assert 客户.get("/api/窗型").json()["窗代"] == 1

    
    排 = 客户.post("/api/排水", json={}).json()
    assert 排["排水"][0]["新关窗"] >= 1
    水位前 = 客户.get("/api/水位线").json()[0]["事件时水位"]
    客户.post("/api/排水", json={"推进到事件时": "2026-11-22T12:00:00Z"})
    assert 客户.get("/api/水位线").json()[0]["事件时水位"] == 水位前  

    r = 客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    assert r.status_code == 200 and r.json()["窗代"] == 2

    史 = 客户.get("/api/窗参史").json()
    assert [(s["代"], s["窗型"], s["滑动步长秒"]) for s in 史] == [(1, "翻滚", 60), (2, "滑动", 30)]

    报 = 客户.post("/api/装载/夹具", params={"名": "滑动窗样例"}).json()
    assert 报["窗代"] == 2

    
    窗 = {w["窗键"]: w for w in 客户.get("/api/热度窗").json()}
    assert 窗["房A|g1|2026-11-22T12:00:00Z"]["点赞合计"] == 3
    assert all(w["窗代"] == 2 for k, w in 窗.items() if "|g2|" in k)
    assert not _库行(客户, "SELECT 房间键, COUNT(DISTINCT 窗代) c FROM 热度窗 WHERE 状态='开启' GROUP BY 房间键 HAVING c>1")

    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]


def test_非法窗参_400(客户):
    for 体 in [
        {"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 7},     
        {"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 0},     
        {"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 90},    
        {"窗型": "滑动", "窗长秒": 60},                       
        {"窗型": "跳动", "窗长秒": 60, "滑动步长秒": 60},    
    ]:
        r = 客户.post("/api/窗参", json=体)
        assert r.status_code == 400, (体, r.text)
        assert r.json()["detail"]["失败闭"]
    assert 客户.get("/api/窗型").json()["窗型"] == "翻滚"  


def test_手改站规致失效_入流失败闭(客户):
    import os

    assert 客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30}).status_code == 200
    conn = sqlite3.connect(os.environ["数据目录"] + "/播浪.db")
    conn.execute("UPDATE 站规 SET 值='7' WHERE 键='滑动步长秒'")
    conn.commit()
    conn.close()
    参 = 客户.get("/api/窗型").json()
    assert 参["valid"] is False and 参["问题"]
    r = 客户.post("/api/装载", json={"批次编号": "批-坏参", "事件": [_事件("坏1", "2026-11-22T12:20:00Z")]})
    assert r.status_code == 409 and r.json()["detail"]["失败闭"]




def test_滑动多窗_迟到修正逐窗发撤回(客户):
    客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    _装(客户, "批-s1", [_事件("s1", "2026-11-22T12:00:10Z", 3)])   
    _装(客户, "批-s2", [_事件("s2", "2026-11-22T12:00:55Z", 1)])   
    报 = _装(客户, "批-s3", [_事件("s3", "2026-11-22T12:00:20Z", 2)])  
    明 = 报["明细"][0]
    assert 明["命运"] == "迟到修正撤回" and 明["修正窗数"] == 1 and 明["窗数"] == 2
    撤 = 客户.get("/api/撤回单").json()
    assert len(撤) == 1 and 撤[0]["窗键"] == "房A|g2|2026-11-22T11:59:30Z" and 撤[0]["新点赞"] == 5
    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]


def test_原子旁路_以最旧窗旁路界整事件旁路(客户):
    客户.post("/api/窗参", json={"窗型": "滑动", "窗长秒": 60, "滑动步长秒": 30})
    _装(客户, "批-b1", [_事件("b1", "2026-11-22T12:01:20Z", 1)])  
    
    
    报 = _装(客户, "批-b2", [_事件("b2", "2026-11-22T12:00:20Z", 9)])
    assert 报["旁路"] == 1 and 报["入窗"] == 0
    明 = 报["明细"][0]
    assert 明["命运"] == "已旁路" and len(明["窗键集本应"]) == 2
    assert not _库行(客户, "SELECT * FROM 事件窗联 WHERE 事件编号='b2'")
    验 = 客户.post("/api/贯验").json()
    assert 验["是否通过"], 验["问题"]




def test_并发_改步长与入流不得半截双套窗键(库):
    from app.services import 装载, 窗参, 贯验

    窗参.改窗参("滑动", 60, 30)
    装载.装一批({"批次编号": "批-c0", "事件": [_事件("c0", "2026-11-22T12:00:05Z", 1)]})  

    错 = []

    def 入流(i):
        try:
            装载.装一批({
                "批次编号": f"批-c{i}",
                "事件": [_事件(f"c{i}a", f"2026-11-22T12:0{1+i}:10Z", 1),
                         _事件(f"c{i}b", f"2026-11-22T12:0{1+i}:40Z", 2)],
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
    for i in range(1, 6):
        线程 += [threading.Thread(target=入流, args=(i,)), threading.Thread(target=改参, args=(i,))]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join()
    assert not 错, 错

    
    assert not _库行(库, "SELECT 房间键, COUNT(DISTINCT 窗代) c FROM 热度窗 WHERE 状态='开启' GROUP BY 房间键 HAVING c>1")
    for r in _库行(库, "SELECT 批次编号, COUNT(DISTINCT 窗代) c FROM 互动事件 WHERE 命运='已入窗' GROUP BY 批次编号"):
        assert r["c"] == 1, f"批{r['批次编号']}半截双代"
    验 = 贯验.跑贯验()
    assert 验["是否通过"], 验["问题"]


def test_演练_改步长并发(客户):
    r = 客户.post("/api/演练/改步长并发")
    assert r.status_code == 200, r.text
    体 = r.json()
    assert 体["结论"] == "通过", 体
    
    参 = 客户.get("/api/窗型").json()
    assert 参["窗型"] == "滑动" and 参["滑动步长秒"] == 20 and 参["valid"]
    assert len(客户.get("/api/窗参史").json()) >= 3
