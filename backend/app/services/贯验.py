from app.db import 连接
from app.seed import 此刻
from app.services import 时间
from app.modules import 滑动窗切分


def 跑贯验() -> dict:
    """窗输出与撤回互证（多窗归属口径）：

    - 已关闭窗的点赞/送礼/笔数 = 经事件窗联落入该窗的已入窗事件合计
    - 有撤回则末次撤回的新值须与窗表一致
    - 旁路事件不得挂窗键、不得有窗联行
    - 同一房不得同时有两代及以上开启窗（不得双套窗键并存关窗）
    - 每个已入窗事件的窗键集，须与其窗代窗参重算结果一致（防步长漂移/新旧混算）
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

        通过 = 1 if not 问题 else 0
        说明 = "窗输出与事件/撤回互证通过（含窗键集重算、双代开启核查）" if 通过 else "；".join(问题)[:800]
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

