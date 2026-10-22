"""本地教学认证：scrypt 密码哈希、SQL 中只保存随机会话/CSRF 的摘要。"""

import hashlib
import secrets

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.db import Session, User, now
from backend.service import ServiceError, digest, uid


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=5).hex()
    return salt + ":" + value


class Auth:
    def __init__(self, runtime):
        self.runtime = runtime
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    def login(self, username, password, register=False):
        username = username.lower()
        with self.runtime.sessions() as session:
            if register:
                user = User(id=uid(), username=username, password_hash=hash_password(password))
                session.add(user)
                try:
                    session.commit()
                except IntegrityError as exc:
                    raise ServiceError(409, "username_exists", "用户名已存在") from exc
            else:
                user = session.scalar(select(User).where(User.username == username))
                # Always perform password work, including nonexistent accounts.
                stored = user.password_hash if user else self.dummy_hash
                valid = secrets.compare_digest(hash_password(password, stored.split(":")[0]), stored)
                if not user or not valid:
                    raise ServiceError(401, "invalid_credentials", "用户名或密码错误")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            session.add(
                Session(
                    token_hash=digest(token),
                    user_id=user.id,
                    csrf_hash=digest(csrf),
                    expires_at=now() + 86400,
                )
            )
            session.commit()
            return {"user": {"id": user.id, "username": user.username}, "csrf_token": csrf}, token

    def identity(self, request, write=False):
        token = request.cookies.get("lab_session", "")
        with self.runtime.sessions() as session:
            auth = session.get(Session, digest(token))
            if not auth or auth.expires_at <= now():
                raise ServiceError(401, "unauthorized", "请先登录")
            if write and not secrets.compare_digest(
                auth.csrf_hash, digest(request.headers.get("x-csrf-token", ""))
            ):
                raise ServiceError(403, "csrf_failed", "CSRF 校验失败")
            user = session.get(User, auth.user_id)
            if not user:
                raise ServiceError(401, "unauthorized", "请先登录")
            return {"id": user.id, "username": user.username}

    def refresh(self, request):
        user = self.identity(request)
        csrf = secrets.token_urlsafe(32)
        with self.runtime.sessions() as session, session.begin():
            auth = session.get(Session, digest(request.cookies["lab_session"]))
            auth.csrf_hash = digest(csrf)
        return {"user": user, "csrf_token": csrf}

    def logout(self, request):
        self.identity(request, write=True)
        with self.runtime.sessions() as session, session.begin():
            session.execute(
                delete(Session).where(Session.token_hash == digest(request.cookies["lab_session"]))
            )
