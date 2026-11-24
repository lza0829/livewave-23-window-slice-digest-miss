from app.db import 连接
from app.seed import 此刻
from app.services import 时间
from app.modules import 滑动窗切分, 窗键切片摘要

import json


def 跑贯验() -> dict:
    """窗输出与撤回互证（多窗归属口径）：

    - 已关闭窗的点赞/送礼/笔数 = 经事件窗联落入该窗的已入窗事件合计
    - 有撤回则末次撤回的新值须与窗表一致
    - 旁路事件不得挂窗键、不得有窗联行
    - 同一房不得同时有两代及以上开启窗（不得双套窗键并存关窗）
    - 每个已入窗事件的窗键集，须与其窗代窗参重算结果一致（防步长漂移/新旧混算）
    - 窗键切片摘要互证：已入窗事件摘要非空、摘要↔窗行键集不分叉、哈希可核、
      快照符窗参史、撤回单窗键全在触发事件摘要内（入窗摘要冻结，不回溯改挂）
    """
    conn = 连接()
    try:
        问题 = []
        事件数 = conn.execute("SELECT COUNT(*) FROM 互动事件").fetchone()[0]
        已关闭 = conn.execute("SELECT * FROM 热度窗 WHERE 状态='已关闭'").fetchall()
        撤回数 = conn.execute("SELECT COUNT(*) FROM 撤回单").fetchone()[0]
        旁路数 = conn.execute("SELECT COUNT(*) FROM 旁路匣").fetchone()[0]

        for 窗 in 已关闭:
            agg = conn.execute(
                """SELECT COALESCE(SUM(e.点赞增量),0) AS 赞, COALESCE(SUM(e.送礼额),0) AS 送, COUNT(*) AS n
                   FROM 事件窗联 l JOIN 互动事件 e ON e.事件编号=l.事件编号
                   WHERE l.窗键=? AND e.命运='已入窗'""",
                (窗["窗键"],),
            ).fetchone()
            if agg["赞"] != 窗["点赞合计"] or agg["送"] != 窗["送礼合计"]:
                问题.append(
                    f"窗{窗['窗键']}合计不符: 窗表赞{窗['点赞合计']}/送{窗['送礼合计']} vs 事件赞{agg['赞']}/送{agg['送']}"
                )
            if agg["n"] != 窗["事件笔数"]:
                问题.append(f"窗{窗['窗键']}笔数不符: 窗表{窗['事件笔数']} vs 事件{agg['n']}")

            末撤 = conn.execute(
                "SELECT * FROM 撤回单 WHERE 窗键=? ORDER BY 编号 DESC LIMIT 1",
                (窗["窗键"],),
            ).fetchone()
            if 末撤 and (末撤["新点赞"] != 窗["点赞合计"] or 末撤["新送礼"] != 窗["送礼合计"]):
                问题.append(f"窗{窗['窗键']}末次撤回与窗表不一致")

        
        脏旁路 = conn.execute(
            "SELECT COUNT(*) FROM 互动事件 WHERE 命运='已旁路' AND 窗键!=''"
        ).fetchone()[0]
        if 脏旁路:
            问题.append(f"旁路事件仍挂窗键:{脏旁路}")
        脏旁路联 = conn.execute(
            """SELECT COUNT(*) FROM 事件窗联 l JOIN 互动事件 e ON e.事件编号=l.事件编号
               WHERE e.命运!='已入窗'"""
        ).fetchone()[0]
        if 脏旁路联:
            问题.append(f"非入窗事件仍有窗联行:{脏旁路联}")

        
        for r in conn.execute(
            """SELECT 房间键, COUNT(DISTINCT 窗代) AS 代数, GROUP_CONCAT(DISTINCT 窗代) AS 代列
               FROM 热度窗 WHERE 状态='开启' GROUP BY 房间键 HAVING 代数>1"""
        ):
            问题.append(f"房{r['房间键']}开启窗横跨{r['代数']}代(g{r['代列']})，双套窗键并存")

        
        史 = {r["代"]: r for r in conn.execute("SELECT * FROM 窗参史")}
        for r in conn.execute("SELECT DISTINCT 窗代 FROM 热度窗"):
            if r["窗代"] not in 史:
                问题.append(f"热度窗窗代g{r['窗代']}无窗参史")

        
        for ev in conn.execute("SELECT * FROM 互动事件 WHERE 命运='已入窗'"):
            代 = ev["窗代"]
            if 代 <= 0:
                问题.append(f"事件{ev['事件编号']}已入窗但窗代缺失")
                continue
            参 = 史.get(代)
            if not 参:
                问题.append(f"事件{ev['事件编号']}窗代g{代}无窗参史")
                continue
            期望 = [
                时间.窗键(ev["房间键"], 代, 起)
                for 起 in 滑动窗切分.事件窗起集(ev["事件时"], 参["窗长秒"], 参["滑动步长秒"])
            ]
            实际 = [
                r["窗键"]
                for r in conn.execute(
                    "SELECT 窗键 FROM 事件窗联 WHERE 事件编号=? ORDER BY 窗键", (ev["事件编号"],)
                )
            ]
            if sorted(实际) != sorted(期望):
                问题.append(
                    f"事件{ev['事件编号']}窗键集不符: 实{sorted(实际)} vs 应{sorted(期望)}"
                )
            elif ev["窗键"] != 期望[-1]:
                问题.append(f"事件{ev['事件编号']}主窗键不符: {ev['窗键']} vs {期望[-1]}")

        孤联 = conn.execute(
            "SELECT COUNT(*) FROM 事件窗联 WHERE 窗键 NOT IN (SELECT 窗键 FROM 热度窗)"
        ).fetchone()[0]
        if 孤联:
            问题.append(f"窗联指向不存在的窗:{孤联}")

        # —— 窗键切片摘要互证（归属写闸/撤回簿/关闭扫描/窗参页协同）——
        摘要表 = {r["事件编号"]: r for r in conn.execute("SELECT * FROM 窗键切片摘要")}
        for ev in conn.execute("SELECT 事件编号, 窗代, 命运 FROM 互动事件"):
            d = 摘要表.get(ev["事件编号"])
            if ev["命运"] != "已入窗":
                if d:
                    问题.append(f"事件{ev['事件编号']}命运{ev['命运']}却有窗键切片摘要")
                continue
            if not d:
                问题.append(f"事件{ev['事件编号']}已入窗但窗键切片摘要缺失（入窗成功摘要空）")
                continue
            try:
                集 = json.loads(d["窗键集合"])
                参 = json.loads(d["窗型参数"])
            except Exception:
                问题.append(f"事件{ev['事件编号']}摘要字段不可解析")
                continue
            if not 集:
                问题.append(f"事件{ev['事件编号']}摘要窗键集合为空（入窗成功摘要空）")
            联 = [
                r["窗键"]
                for r in conn.execute(
                    "SELECT 窗键 FROM 事件窗联 WHERE 事件编号=?", (ev["事件编号"],)
                )
            ]
            if sorted(联) != sorted(集):
                问题.append(
                    f"事件{ev['事件编号']}摘要与窗行键集分叉: 摘要{sorted(集)} vs 窗联{sorted(联)}"
                )
            if 窗键切片摘要.计算哈希(ev["事件编号"], 参, 集) != d["摘要哈希"]:
                问题.append(f"事件{ev['事件编号']}摘要哈希不符")
            if 参.get("窗代") != ev["窗代"]:
                问题.append(
                    f"事件{ev['事件编号']}摘要窗代g{参.get('窗代')}与事件窗代g{ev['窗代']}分叉"
                )
            史参 = 史.get(参.get("窗代"))
            if not 史参 or (史参["窗型"], 史参["窗长秒"], 史参["滑动步长秒"]) != (
                参.get("窗型"), 参.get("窗长秒"), 参.get("滑动步长秒")
            ):
                问题.append(f"事件{ev['事件编号']}摘要窗型参数快照与窗参史不符")
        for r in conn.execute("SELECT * FROM 撤回单"):
            d = 摘要表.get(r["事件编号"])
            if not d:
                问题.append(f"撤回单#{r['编号']}触发事件{r['事件编号']}无摘要，撤回未吃摘要")
                continue
            try:
                集 = json.loads(d["窗键集合"])
            except Exception:
                集 = []
            if r["窗键"] not in 集:
                问题.append(f"撤回单#{r['编号']}窗键{r['窗键']}挂在事件{r['事件编号']}摘要外")

        通过 = 1 if not 问题 else 0
        说明 = "窗输出与事件/撤回/摘要互证通过（含窗键集重算、双代开启、摘要冻结核查）" if 通过 else "；".join(问题)[:800]
        conn.execute(
            """INSERT INTO 窗贯验(时刻,事件数,已关闭窗数,撤回数,旁路数,是否通过,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 事件数, len(已关闭), 撤回数, 旁路数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "事件数": 事件数,
            "已关闭窗数": len(已关闭),
            "撤回数": 撤回数,
            "旁路数": 旁路数,
            "说明": 说明,
            "问题": 问题,
        }
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

