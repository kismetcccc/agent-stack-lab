"""显式、可重复的版本化迁移入口。新增版本应追加迁移而不是修改已发布版本。"""

from backend.config import Settings
from backend.db import Base, SchemaVersion, connect


def migrate(engine):
    # v1 初始 schema；create_all 只用于这个显式初始迁移，不在 API 启动调用。
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        if session.get(SchemaVersion, 1) is None:
            session.add(SchemaVersion(version=1))


if __name__ == "__main__":
    engine, _ = connect(Settings().database_url)
    migrate(engine)
    print("schema version 1 applied")
