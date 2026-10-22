"""集中声明状态机；没有隐式取消或 exactly-once 承诺。"""

TRANSITIONS = {
    "pending": {"ready"},
    "ready": {"running"},
    "running": {"succeeded", "retry_wait", "failed"},
    "retry_wait": {"ready"},
    "succeeded": set(),
    "failed": set(),
}


def transition(task, target):
    if target not in TRANSITIONS[task.status]:
        raise ValueError(f"invalid transition {task.status} -> {target}")
    task.status = target


class PermanentError(Exception):
    pass


class TransientError(Exception):
    pass
