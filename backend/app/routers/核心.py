import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.services import 装载, 贯验, 目录, 窗参, 演练

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    事件: list = Field(default_factory=list)


class 窗参请求(BaseModel):
    窗型: str
    窗长秒: int
    滑动步长秒: int | None = None


class 排水请求(BaseModel):
    房间键: str | None = None
    推进到事件时: str | None = None


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "播浪",
        "骨架": "互动事件入流→事件时间水位线推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/直播间")
def 列直播间():
    conn = 连接()
    try:
        rooms = [dict(r) for r in conn.execute("SELECT * FROM 直播间 ORDER BY 房间键")]
        for r in rooms:
            wm = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (r["房间键"],)).fetchone()
            r["水位线"] = dict(wm) if wm else None
        return rooms
    finally:
        conn.close()


@路由.get("/事件")
def 列事件(命运: str = ""):
    conn = 连接()
    try:
        if 命运:
            rows = conn.execute(
                "SELECT * FROM 互动事件 WHERE 命运=? ORDER BY 事件时 DESC LIMIT 200", (命运,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM 互动事件 ORDER BY 事件时 DESC LIMIT 200").fetchall()
        窗数 = {
            r["事件编号"]: r["c"]
            for r in conn.execute("SELECT 事件编号, COUNT(*) AS c FROM 事件窗联 GROUP BY 事件编号")
        }
        out = []
        for r in rows:
            d = dict(r)
            d["窗数"] = 窗数.get(r["事件编号"], 0)
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/水位线")
def 列水位线():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 水位线 ORDER BY 房间键")]
    finally:
        conn.close()


@路由.get("/热度窗")
def 列热度窗(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 热度窗 WHERE 状态=? ORDER BY 窗起事件时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 热度窗 ORDER BY 窗起事件时 DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/撤回单")
def 列撤回():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 撤回单 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/旁路匣")
def 列旁路():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁路匣 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.post("/装载")
def 做装载(体: 装载请求):
    return 装载.装一批(体.model_dump())


@路由.post("/装载/夹具")
def 装夹具(名: str = "准时热度样例"):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    return 装载.装一批(json.loads(路径.read_text(encoding="utf-8")))


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 窗贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()


@路由.get("/窗型")
def 取窗型():
    """窗型只读接口：窗型/窗长/步长/窗代/每事件窗数/valid。"""
    conn = 连接()
    try:
        return 窗参.当前窗参(conn)
    finally:
        conn.close()


@路由.get("/窗键集")
def 取窗键集(事件时: str, 房间键: str = ""):
    """事件窗键集只读接口：同一事件在现行窗参下落入的窗键集合（两口径可区分）。"""
    conn = 连接()
    try:
        参 = 窗参.当前窗参(conn)
        if not 参["valid"]:
            raise HTTPException(409, detail={"失败闭": True, "原因": "窗参失效", "问题": 参["问题"]})
        if not 房间键:
            房 = conn.execute("SELECT 房间键 FROM 直播间 ORDER BY 房间键 LIMIT 1").fetchone()
            if not 房:
                raise HTTPException(404, "无直播间")
            房间键 = 房["房间键"]
        集 = 窗参.事件窗键集(房间键, 事件时, 参)
        return {
            "房间键": 房间键,
            "事件时": 事件时,
            "窗型": 参["窗型"],
            "窗代": 参["窗代"],
            "窗长秒": 参["窗长秒"],
            "滑动步长秒": 参["滑动步长秒"],
            "主窗键": 集[-1],
            "事件窗键集": 集,
            "窗数": len(集),
        }
    finally:
        conn.close()


@路由.post("/窗参")
def 改窗参(体: 窗参请求):
    """换代改窗参；有开启窗则失败闭（409），窗参非法则 400。"""
    return 窗参.改窗参(体.窗型, 体.窗长秒, 体.滑动步长秒)


@路由.get("/窗参史")
def 列窗参史():
    conn = 连接()
    try:
        return 窗参.窗参史(conn)
    finally:
        conn.close()


@路由.post("/排水")
def 做排水(体: 排水请求):
    """推进水位清场（默认+一个窗长），全部开启窗按水位>=窗止关闭。"""
    return 窗参.排水(体.房间键, 体.推进到事件时)


@路由.post("/演练/改步长并发")
def 做演练():
    return 演练.改步长并发演练()


@路由.get("/空桩")
def 空桩():
    from app import modules

    return modules.列表()

from app.modules import 窗键切片摘要 as 切


@路由.get("/核证/窗键切片")
def 取窗键切片(事件编号: str | None = None):
    conn = 连接()
    try:
        return 切.查切片(conn, 事件编号)
    finally:
        conn.close()

def _alias_payload(payload: dict) -> dict:
    out = dict(payload or {})
    if "窗键" in out and "window_key" not in out:
        out["window_key"] = out.get("窗键")
    if "房间键" in out and "room_key" not in out:
        out["room_key"] = out.get("房间键")
    if "事件编号" in out and "event_id" not in out:
        out["event_id"] = out.get("事件编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows(rows: list) -> list:
    return [_alias_payload(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_23(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "livewave", "nn": "23"}
    if extra:
        data.update(extra)
    return data

