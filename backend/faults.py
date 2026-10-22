"""仅故障验收使用的显式进程环境开关，默认关闭，无 HTTP 入口。"""

import os
import time
from pathlib import Path


def pause_at(point):
    if os.getenv("LAB_TEST_HOOKS") != "true" or os.getenv("LAB_TEST_PAUSE_AT") != point:
        return
    allowed = {"after_inbox_commit", "after_mongo_save", "after_claim", "after_outbox_publish"}
    if point not in allowed:
        raise ValueError("unknown fault point")
    # Fixed /tmp path, no user-controlled arbitrary path; bounded pause for kill/restart tests.
    Path("/tmp/lab-hook-" + point).write_text(str(os.getpid()))
    time.sleep(60)
