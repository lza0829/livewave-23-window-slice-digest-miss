from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 窗键切片摘要 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  事件编号 TEXT NOT NULL,
  窗型参数 TEXT NOT NULL DEFAULT '',
  窗键集合 TEXT NOT NULL DEFAULT '[]',
  摘要哈希 TEXT NOT NULL DEFAULT '',
  批号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL DEFAULT ''
);
-- 入窗摘要冻结：一事件一摘要，钉死不可改挂
CREATE UNIQUE INDEX IF NOT EXISTS 窗键切片摘要_事件编号_uq ON 窗键切片摘要(事件编号);

CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 直播间 (
  房间键 TEXT PRIMARY KEY,
  标题 TEXT NOT NULL,
  主播 TEXT NOT NULL,
  开播事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '直播中'
);
CREATE TABLE IF NOT EXISTS 互动事件 (
  事件编号 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  事件类型 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  观众键 TEXT NOT NULL DEFAULT '',
  点赞增量 INTEGER NOT NULL DEFAULT 0,
  送礼额 INTEGER NOT NULL DEFAULT 0,
  命运 TEXT NOT NULL DEFAULT '已入流',
  窗键 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  窗代 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 水位线 (
  房间键 TEXT PRIMARY KEY REFERENCES 直播间(房间键),
  事件时水位 TEXT NOT NULL,
  允许迟到秒 INTEGER NOT NULL DEFAULT 30,
  更新处理时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 热度窗 (
  窗键 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  窗起事件时 TEXT NOT NULL,
  窗止事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '开启',
  点赞合计 INTEGER NOT NULL DEFAULT 0,
  送礼合计 INTEGER NOT NULL DEFAULT 0,
  事件笔数 INTEGER NOT NULL DEFAULT 0,
  关闭处理时 TEXT NOT NULL DEFAULT '',
  版本 INTEGER NOT NULL DEFAULT 0,
  窗代 INTEGER NOT NULL DEFAULT 1,
  窗型 TEXT NOT NULL DEFAULT '翻滚'
);
CREATE TABLE IF NOT EXISTS 事件窗联 (
  事件编号 TEXT NOT NULL REFERENCES 互动事件(事件编号),
  窗键 TEXT NOT NULL REFERENCES 热度窗(窗键),
  PRIMARY KEY (事件编号, 窗键)
);
CREATE TABLE IF NOT EXISTS 窗参史 (
  代 INTEGER PRIMARY KEY,
  窗型 TEXT NOT NULL,
  窗长秒 INTEGER NOT NULL,
  滑动步长秒 INTEGER NOT NULL,
  生效处理时 TEXT NOT NULL,
  备注 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 撤回单 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  窗键 TEXT NOT NULL,
  房间键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  旧点赞 INTEGER NOT NULL,
  新点赞 INTEGER NOT NULL,
  旧送礼 INTEGER NOT NULL,
  新送礼 INTEGER NOT NULL,
  处理时 TEXT NOT NULL,
  事件编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 旁路匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 窗贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  事件数 INTEGER NOT NULL,
  已关闭窗数 INTEGER NOT NULL,
  撤回数 INTEGER NOT NULL,
  旁路数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
"""

默认站规 = {
    "站名": "播浪",
    "窗型": "翻滚",
    "窗长秒": "60",
    "滑动步长秒": "60",
    "窗代": "1",
    "允许迟到秒": "30",
    "水位推进策略": "事件时最大值",
    "关窗条件": "水位>=窗止即关闭发射",
    "旁路条件": "水位>=窗止+允许迟到（滑动窗取事件窗键集最旧一扇的旁路界，整事件原子旁路）",
    "窗归属口径": "窗起按滑动步长对齐；翻滚=步长等于窗长恰落1窗；滑动多窗归属，整集原子",
    "骨架": "互动事件入流→事件时间水位线推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
}


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _补列(conn, 表: str, 列: str, 定义: str) -> None:
    已有 = [r[1] for r in conn.execute(f"PRAGMA table_info({表})")]
    if 列 not in 已有:
        conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    
    _补列(conn, "互动事件", "窗代", "INTEGER NOT NULL DEFAULT 0")
    _补列(conn, "热度窗", "窗代", "INTEGER NOT NULL DEFAULT 1")
    _补列(conn, "热度窗", "窗型", "TEXT NOT NULL DEFAULT '翻滚'")
    for k, v in 默认站规.items():
        conn.execute("INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 窗参史").fetchone()["c"] == 0:
        窗长 = int(conn.execute("SELECT 值 FROM 站规 WHERE 键='窗长秒'").fetchone()["值"])
        conn.execute(
            "INSERT INTO 窗参史(代, 窗型, 窗长秒, 滑动步长秒, 生效处理时, 备注) VALUES (?,?,?,?,?,?)",
            (1, "翻滚", 窗长, 窗长, 此刻(), "初始窗参：翻滚，步长=窗长"),
        )
    if conn.execute("SELECT COUNT(*) AS c FROM 直播间").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO 直播间(房间键, 标题, 主播, 开播事件时, 状态) VALUES (?,?,?,?,?)",
            ("房A", "晚间热聊", "主播小浪", "2026-11-22T12:00:00Z", "直播中"),
        )
        conn.execute(
            "INSERT INTO 水位线(房间键, 事件时水位, 允许迟到秒, 更新处理时) VALUES (?,?,?,?)",
            ("房A", "2026-11-22T12:00:00Z", 30, 此刻()),
        )
    conn.commit()
    conn.close()
