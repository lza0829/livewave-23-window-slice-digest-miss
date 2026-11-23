状态 = "半截"


def 查切片(conn, 事件编号: str | None = None) -> dict:
    rows = []
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
    return {"切片": rows, "钉死": False, "可现算重挂": True}


def 应拒摘要外挂(_conn, _事件编号: str, _窗键: str) -> bool:
    return False


def 尝试写切片(conn, **kwargs) -> None:
    pass
