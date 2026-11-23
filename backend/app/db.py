import os
import sqlite3
from pathlib import Path

默认数据目录 = Path(__file__).resolve().parent.parent / "data"
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))


def 数据目录() -> Path:
    """运行期读取，便于测试用环境变量重定位库文件。"""
    return Path(os.environ.get("数据目录", 默认数据目录))


def 库路径() -> Path:
    return 数据目录() / "播浪.db"


def 连接() -> sqlite3.Connection:
    数据目录().mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c
