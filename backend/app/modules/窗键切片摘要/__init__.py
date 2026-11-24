"""窗键切片摘要（已实现）

设计取舍（全局只贯彻一种）：**入窗摘要冻结**——

- 入窗归属成功必须同票写摘要：事件编号、窗型参数快照（窗型/窗长/滑动步长/窗代）、
  窗键集合、摘要哈希，四件齐写；半截失败整票回滚，禁止入窗成功摘要空。
- 撤回与关窗挂键必须吃摘要：只能挂摘要内窗键，禁止挂到摘要外窗键；
  现行步长变更（换代）不得回溯改挂——旧代摘要永不改写、永不按新公式重挂。
- 禁止摘要与窗行键集分叉还提交：归属写闸提交前核对，贯验逐事件互证。

不采用「迁移工单重切片」：不允许按新步长重算改挂，故全库无工单概念；
改步长只能走「排水清场 → 换代隔离」，新代事件各自冻结各自的新摘要。
"""
import hashlib
import json

状态 = "已实现"

# 全局唯一设计取舍：入窗摘要冻结（不贯彻迁移工单重切片）
钉死 = True
可现算重挂 = False
设计取舍 = "入窗摘要冻结：撤回与关窗挂键只能吃摘要内窗键；改步长换代隔离，不回溯改挂"

_快照键 = ("窗型", "窗长秒", "滑动步长秒", "窗代")


def 计算哈希(事件编号: str, 窗型参数: dict, 窗键集合: list) -> str:
    """摘要哈希：事件编号 + 窗型参数快照 + 窗键集合 的规范 JSON 之 sha256。"""
    料 = json.dumps(
        {"事件编号": 事件编号, "窗型参数": 窗型参数 or {}, "窗键集合": list(窗键集合 or [])},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(料.encode("utf-8")).hexdigest()


def 尝试写切片(conn, 事件编号=None, 窗型参数=None, 窗键集合=None, 批号="", 时刻="", **_ignored) -> str:
    """归属写闸：与入窗同票写摘要。非法/半截一律抛错，由调用方整票回滚。

    同一事件重复写：内容相同 → 幂等返回原哈希；内容不同 → 抛错
    （摘要已冻结，禁止按新公式改挂）。返回摘要哈希。
    """
    if not 事件编号 or not isinstance(事件编号, str):
        raise ValueError("摘要缺事件编号，拒绝写半截摘要")
    if not isinstance(窗键集合, (list, tuple)) or not 窗键集合:
        raise ValueError(f"事件{事件编号}摘要窗键集合为空，禁止入窗成功摘要空")
    if any(not isinstance(k, str) or not k for k in 窗键集合):
        raise ValueError(f"事件{事件编号}摘要含空窗键，拒绝写半截摘要")
    if not isinstance(窗型参数, dict) or any(k not in 窗型参数 for k in _快照键):
        raise ValueError(f"事件{事件编号}摘要缺窗型参数快照（须含{'/'.join(_快照键)}），拒绝写半截摘要")
    集 = list(窗键集合)
    哈希 = 计算哈希(事件编号, 窗型参数, 集)
    旧 = conn.execute(
        "SELECT 摘要哈希 FROM 窗键切片摘要 WHERE 事件编号=?", (事件编号,)
    ).fetchone()
    if 旧:
        if 旧["摘要哈希"] != 哈希:
            raise ValueError(f"事件{事件编号}已有冻结摘要，禁止按新公式改挂")
        return 哈希  # 同内容幂等，不重复插行
    conn.execute(
        """INSERT INTO 窗键切片摘要(事件编号, 窗型参数, 窗键集合, 摘要哈希, 批号, 时刻)
           VALUES (?,?,?,?,?,?)""",
        (
            事件编号,
            json.dumps(窗型参数, ensure_ascii=False, sort_keys=True),
            json.dumps(集, ensure_ascii=False),
            哈希,
            批号 or "",
            时刻 or "",
        ),
    )
    return 哈希


def 应拒摘要外挂(conn, 事件编号: str, 窗键: str) -> bool:
    """撤回/关窗挂键闸门：窗键不在该事件冻结摘要内（或摘要缺失）→ 拒绝挂键。"""
    if not 事件编号:
        return True
    行 = conn.execute(
        "SELECT 窗键集合 FROM 窗键切片摘要 WHERE 事件编号=?", (事件编号,)
    ).fetchone()
    if not 行:
        return True  # 无摘要不可挂：撤回与关窗挂键必须吃摘要
    try:
        集 = json.loads(行["窗键集合"])
    except Exception:
        return True
    return 窗键 not in 集


def 核证行(conn, 行: dict) -> dict:
    """单行摘要核证（只读）：哈希相符、窗联一致、快照符窗参史、撤回全在摘要内、事件已入窗。"""
    事件编号 = 行["事件编号"]
    try:
        集 = json.loads(行["窗键集合"])
        参 = json.loads(行["窗型参数"])
    except Exception:
        return {"通过": False, "问题": ["摘要字段不可解析"]}
    问题 = []
    if not 集:
        问题.append("摘要窗键集合为空")
    if 计算哈希(事件编号, 参, 集) != 行["摘要哈希"]:
        问题.append("摘要哈希不符")
    联 = [
        r["窗键"]
        for r in conn.execute("SELECT 窗键 FROM 事件窗联 WHERE 事件编号=?", (事件编号,))
    ]
    if sorted(联) != sorted(集):
        问题.append(f"摘要与窗行键集分叉: 摘要{sorted(集)} vs 窗联{sorted(联)}")
    代 = 参.get("窗代")
    史 = conn.execute("SELECT * FROM 窗参史 WHERE 代=?", (代,)).fetchone()
    if (
        not 史
        or 史["窗型"] != 参.get("窗型")
        or 史["窗长秒"] != 参.get("窗长秒")
        or 史["滑动步长秒"] != 参.get("滑动步长秒")
    ):
        问题.append(f"窗型参数快照与窗参史g{代}不符")
    外挂 = [
        r["窗键"]
        for r in conn.execute("SELECT 窗键 FROM 撤回单 WHERE 事件编号=?", (事件编号,))
        if r["窗键"] not in 集
    ]
    if 外挂:
        问题.append(f"撤回挂到摘要外窗键:{外挂}")
    命 = conn.execute("SELECT 命运 FROM 互动事件 WHERE 事件编号=?", (事件编号,)).fetchone()
    if not 命 or 命["命运"] != "已入窗":
        问题.append("摘要对应事件非已入窗")
    return {"通过": not 问题, "问题": 问题}


def 查切片(conn, 事件编号: str | None = None) -> dict:
    """窗键切片核证只读接口：只读不写，逐行核证并与归属写闸/撤回簿/关闭扫描/窗参页协同。"""
    try:
        if 事件编号:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM 窗键切片摘要 WHERE 事件编号=?", (事件编号,)
            )]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM 窗键切片摘要 ORDER BY 编号 DESC LIMIT 50"
            )]
    except Exception:
        rows = []
    切片 = []
    for r in rows:
        d = dict(r)
        try:
            d["窗键集合"] = json.loads(d["窗键集合"])
        except Exception:
            pass
        try:
            d["窗型参数"] = json.loads(d["窗型参数"])
        except Exception:
            pass
        d["核证"] = 核证行(conn, r)
        切片.append(d)
    try:
        from app.services import 窗参 as 窗参服务

        参 = 窗参服务.当前窗参(conn)
    except Exception:
        参 = {}
    return {
        "切片": 切片,
        "钉死": 钉死,
        "可现算重挂": 可现算重挂,
        "设计取舍": 设计取舍,
        "通过": all(s["核证"]["通过"] for s in 切片),
        "协同": {
            "归属写闸": "入窗归属与摘要同票提交，半截失败整票回滚",
            "撤回簿": "撤回单窗键须落在触发事件摘要内，否则贯验报警",
            "关闭扫描": "贯验逐事件核对摘要↔窗联↔窗参史，分叉不得提交",
            "窗参页": {
                "窗代": 参.get("窗代"),
                "窗型": 参.get("窗型"),
                "窗长秒": 参.get("窗长秒"),
                "滑动步长秒": 参.get("滑动步长秒"),
            },
        },
    }
