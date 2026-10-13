import json
import sqlite3
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from fastapi import Request, HTTPException
from . import config
from .db import one, transaction
from .security import now, uid, digest, secure_equal

FOUNDERS={"FUNDADOR"}
MEMBER_ADMINS={"FUNDADOR","ADMIN_MEMBROS"}
OPERATIONS={"FUNDADOR","ADMIN_OPERACIONAL"}
LEADERS={"FUNDADOR","ADMIN_MEMBROS","ADMIN_OPERACIONAL","CAPITAO"}
ADMINS={"FUNDADOR","ADMIN_MEMBROS","ADMIN_OPERACIONAL"}


def error(message, status=400):
    raise HTTPException(status_code=status,detail=message)


def require_origin(request:Request):
    origin=request.headers.get("origin")
    if not origin:
        return
    req_origin=f"{request.url.scheme}://{request.url.netloc}"
    allowed={req_origin,config.PUBLIC_URL}|config.ALLOWED_ORIGINS
    if origin.rstrip("/") not in allowed:
        error("Origem não autorizada",403)


def auth(request:Request, roles=None, allow_pending=False, allow_suspended=False):
    raw=request.cookies.get("fb_session")
    if not raw:
        error("Sessão necessária",401)
    record=one("""SELECT s.csrf_token,s.expires_at,u.id,u.email,u.username,u.ff_uid,u.role,u.status,
                         u.created_at,u.last_seen,u.bio,u.privacy_public
                  FROM sessions s JOIN users u ON u.id=s.user_id
                  WHERE s.token_hash=?""",(digest(raw),))
    if not record or record["expires_at"] < now():
        error("Sessão inválida ou expirada",401)
    if record["status"]=="SUSPENDED" and not allow_suspended:
        error("Conta suspensa",403)
    if record["status"]=="REJECTED":
        error("Conta não aprovada",403)
    if not allow_pending and record["status"]!="ACTIVE":
        error("Aguarda aprovação administrativa",403)
    if roles and record["role"] not in roles:
        error("Permissões insuficientes",403)
    if request.method not in ("GET","HEAD","OPTIONS"):
        require_origin(request)
        csrf=request.headers.get("X-CSRF-Token","")
        if not secure_equal(csrf,record["csrf_token"]):
            error("Token CSRF em falta ou inválido",403)
    # Keep presence fresh without writing on every request.
    if not record["last_seen"] or record["last_seen"] < (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec="seconds"):
        with transaction() as db:
            db.execute("UPDATE users SET last_seen=? WHERE id=?",(now(),record["id"]))
    return record


def audit(db,actor,action,kind,entity_id,details=None):
    db.execute("INSERT INTO audit_log(id,actor_id,action,entity_type,entity_id,detail,created_at) VALUES(?,?,?,?,?,?,?)",
               (uid(),actor,action,kind,entity_id,json.dumps(details or {},ensure_ascii=False),now()))


def notify(db,user_id,kind,body):
    db.execute("INSERT INTO notifications(id,user_id,kind,body,created_at) VALUES(?,?,?,?,?)",
               (uid(),user_id,kind,body,now()))


def public_user(u):
    return {k:v for k,v in u.items() if k not in ("password_hash",)}


def assert_active(db,user_id):
    row=db.execute("SELECT id,status FROM users WHERE id=?",(user_id,)).fetchone()
    if not row or row["status"]!="ACTIVE":
        error("Membro inexistente ou inativo",404)
    return row


def check_length(value,min_n,max_n,label):
    value=value.strip()
    if len(value)<min_n or len(value)>max_n:
        error(f"{label}: entre {min_n} e {max_n} caracteres")
    return value
