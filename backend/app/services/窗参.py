"""窗参（窗型/窗长/滑动步长/窗代）的读、改、排水。

硬约束：
- 窗型是全局架构选择，同一房同一时段不得翻滚/滑动混算；
- 改窗型或改步长：存在开启窗 → 失败闭（409）；无开启窗 → 换代，
  旧窗键含旧窗代，历史明确隔离，永不混算；
- 与入流并发：装载/改参/排水共用「锁」，一批要么全旧代要么全新代，
  不得半截双套窗键；关窗只在单代开启窗上进行（水位>=窗止）。
"""
import threading

from fastapi import HTTPException

from app.db import 连接
from app.seed import 此刻
from app.services import 时间, 热度窗
from app.modules import 滑动窗切分


锁 = threading.Lock()


def 当前窗参(conn) -> dict:
    """读站规+窗参史并校验；valid=False 时入流与换代都失败闭。"""
    站 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    问题 = []
    try:
        窗型 = 站.get("窗型", "翻滚")
        窗长秒 = int(站.get("窗长秒", "60"))
        滑动步长秒 = int(站.get("滑动步长秒", str(窗长秒)))
        窗代 = int(站.get("窗代", "1"))
    except ValueError as e:
        return {"窗型": "", "窗长秒": 0, "滑动步长秒": 0, "窗代": 0,
                "每事件窗数": None, "valid": False, "问题": [f"窗参非数值:{e}"]}
    问题.extend(滑动窗切分.校验窗参(窗型, 窗长秒, 滑动步长秒))
    史 = conn.execute("SELECT * FROM 窗参史 WHERE 代=?", (窗代,)).fetchone()
    if not 史:
        问题.append(f"窗参史缺第{窗代}代")
    elif (史["窗型"] != 窗型 or 史["窗长秒"] != 窗长秒 or 史["滑动步长秒"] != 滑动步长秒):
        问题.append(f"站规与窗参史第{窗代}代不一致")
    return {
        "窗型": 窗型,
        "窗长秒": 窗长秒,
        "滑动步长秒": 滑动步长秒,
        "窗代": 窗代,
        "每事件窗数": None if 问题 else 滑动窗切分.每事件窗数(窗长秒, 滑动步长秒),
        "valid": not 问题,
        "问题": 问题,
    }


def 事件窗键集(房间键: str, 事件时: str, 窗参: dict) -> list:
    """事件按现行窗参落入的窗键集（升序，末位主窗）；两口径由此可区分。"""
    return [
        时间.窗键(房间键, 窗参["窗代"], 起)
        for 起 in 滑动窗切分.事件窗起集(事件时, 窗参["窗长秒"], 窗参["滑动步长秒"])
    ]


def 改窗参(窗型: str, 窗长秒: int, 滑动步长秒: int | None) -> dict:
    """换代改参。失败闭：窗参非法→400；有开启窗→409；现行窗参失效→409。"""
    if 窗型 == "翻滚":
        滑动步长秒 = 窗长秒  
    问题 = 滑动窗切分.校验窗参(窗型, 窗长秒, 滑动步长秒 if 滑动步长秒 is not None else 0)
    if 滑动步长秒 is None and 窗型 == "滑动":
        问题.append("滑动窗须给滑动步长秒")
    if 问题:
        raise HTTPException(400, detail={"失败闭": True, "原因": "窗参非法，未生效", "问题": 问题})
    with 锁:
        conn = 连接()
        conn.isolation_level = None  
        try:
            conn.execute("BEGIN IMMEDIATE")
            未了 = conn.execute(
                "SELECT 房间键, COUNT(*) AS c FROM 热度窗 WHERE 状态='开启' GROUP BY 房间键"
            ).fetchall()
            if 未了:
                raise HTTPException(409, detail={
                    "失败闭": True,
                    "原因": "存在开启窗，改窗参被拒绝：先排水关窗，再换代，绝不同房双套窗键",
                    "未了开启窗": [{"房间键": r["房间键"], "开启窗数": r["c"]} for r in 未了],
                })
            旧 = 当前窗参(conn)
            if not 旧["valid"]:
                raise HTTPException(409, detail={
                    "失败闭": True, "原因": "现行窗参已失效，禁止换代", "问题": 旧["问题"],
                })
            if (旧["窗型"], 旧["窗长秒"], 旧["滑动步长秒"]) == (窗型, 窗长秒, 滑动步长秒):
                conn.execute("COMMIT")
                return {"已变更": False, "说明": "窗参未变，不换代", **旧}
            新代 = 旧["窗代"] + 1
            for k, v in {"窗型": 窗型, "窗长秒": str(窗长秒),
                         "滑动步长秒": str(滑动步长秒), "窗代": str(新代)}.items():
                conn.execute("UPDATE 站规 SET 值=? WHERE 键=?", (v, k))
            conn.execute(
                "INSERT INTO 窗参史(代, 窗型, 窗长秒, 滑动步长秒, 生效处理时, 备注) VALUES (?,?,?,?,?,?)",
                (新代, 窗型, 窗长秒, 滑动步长秒, 此刻(),
                 f"由g{旧['窗代']}（{旧['窗型']} {旧['窗长秒']}/{旧['滑动步长秒']}）换代；旧窗键保留旧代隔离"),
            )
            conn.execute("COMMIT")
            return {
                "已变更": True, "窗代": 新代, "窗型": 窗型, "窗长秒": 窗长秒,
                "滑动步长秒": 滑动步长秒,
                "每事件窗数": 滑动窗切分.每事件窗数(窗长秒, 滑动步长秒),
                "说明": f"已换代 g{旧['窗代']}→g{新代}，历史窗键以旧代隔离",
            }
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()


def 排水(房间键: str | None = None, 推进到事件时: str | None = None) -> dict:
    """推进水位（默认+一个窗长）并关窗清场；关窗仍只看水位>=窗止，不回退水位。"""
    with 锁:
        conn = 连接()
        try:
            窗参 = 当前窗参(conn)
            if not 窗参["valid"]:
                raise HTTPException(409, detail={"失败闭": True, "原因": "窗参失效，拒绝排水", "问题": 窗参["问题"]})
            if 房间键:
                行 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchall()
            else:
                行 = conn.execute("SELECT * FROM 水位线").fetchall()
            结果 = []
            for 水位 in 行:
                当前 = 水位["事件时水位"]
                目标 = 推进到事件时 or 时间.加秒(当前, 窗参["窗长秒"])
                if 时间.解析(目标) <= 时间.解析(当前):
                    目标 = 当前  
                else:
                    conn.execute(
                        "UPDATE 水位线 SET 事件时水位=?, 更新处理时=? WHERE 房间键=?",
                        (目标, 此刻(), 水位["房间键"]),
                    )
                关 = 热度窗.尝试关窗(
                    conn, 水位["房间键"], 目标, int(水位["允许迟到秒"]), 窗参["窗长秒"], 此刻()
                )
                结果.append({"房间键": 水位["房间键"], "事件时水位": 目标, "新关窗": 关})
            conn.commit()
            return {"排水": 结果, "窗代": 窗参["窗代"]}
        finally:
            conn.close()


def 窗参史(conn) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM 窗参史 ORDER BY 代")]
