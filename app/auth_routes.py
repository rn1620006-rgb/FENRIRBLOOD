import os
import re
import secrets
import smtplib
from email.message import EmailMessage
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from . import config
from .core import auth, error, require_origin, audit
from .db import one, transaction
from .security import uid, now, future, token, digest,hash_password,check_password

router=APIRouter(prefix="/api/auth",tags=["auth"])

class Register(BaseModel):
    email:str=Field(max_length=254)
    username:str=Field(min_length=2,max_length=40)
    password:str=Field(min_length=12,max_length=256)
    ff_uid:str=Field(default="",max_length=30)

class Login(BaseModel):
    email:str
    password:str

class ChangePassword(BaseModel):
    old_password:str
    new_password:str=Field(min_length=12,max_length=256)

class Recover(BaseModel):
    email:str

class ResetPassword(BaseModel):
    token:str
    password:str=Field(min_length=12,max_length=256)


def normalize_email(value):
    e=value.strip().casefold()
    if len(e)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",e):
        error("Endereço de email inválido")
    return e


def issue_session(db,user_id,response):
    raw=token()
    csrf=token()
    db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES (?,?,?,?,?)",
               (digest(raw),user_id,csrf,now(),future(days=config.SESSION_DAYS)))
    response.set_cookie("fb_session",raw,max_age=config.SESSION_DAYS*86400,
                        httponly=True,secure=config.SECURE_COOKIES,samesite="lax",path="/")
    return csrf

def public_rate_limit(request:Request,scope:str,limit:int,minutes:int):
    # Persistent IP-based limit for unauthenticated public endpoints.
    from datetime import datetime,timezone,timedelta
    ip=request.client.host if request.client else "unknown"
    key=digest(scope+":"+ip)
    cutoff=(datetime.now(timezone.utc)-timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with transaction(immediate=True) as db:
        count=db.execute("SELECT COUNT(*) c FROM login_attempts WHERE key=? AND created_at>=?",(key,cutoff)).fetchone()["c"]
        if count>=limit:
            error("Demasiados pedidos. Tenta novamente mais tarde.",429)
        db.execute("INSERT INTO login_attempts(key,created_at) VALUES(?,?)",(key,now()))

@router.post("/register")
def register(data:Register,request:Request):
    require_origin(request)
    public_rate_limit(request,"register",15,60)
    email=normalize_email(data.email)
    if data.username.strip()!=data.username or not data.username.strip():
        error("Indica um nome de jogador válido")
    if len(data.password)<12:
        error("Palavra-passe demasiado curta")
    user_id=uid()
    with transaction(immediate=True) as db:
        if db.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
            error("Este email já está registado",409)
        db.execute("INSERT INTO users(id,email,password_hash,username,ff_uid,created_at) VALUES(?,?,?,?,?,?)",
                   (user_id,email,hash_password(data.password),data.username.strip(),data.ff_uid.strip(),now()))
        audit(db,user_id,"REGISTER","user",user_id)
    return {"ok":True,"message":"Conta criada. Aguarda aprovação de um administrador."}

@router.post("/login")
def login(data:Login,request:Request,response:Response):
    require_origin(request)
    email=normalize_email(data.email)
    ip=(request.client.host if request.client else "unknown")[:100]
    key=digest(ip+":"+email)
    with transaction(immediate=True) as db:
        cutoff=(__import__('datetime').datetime.now(__import__('datetime').timezone.utc)-__import__('datetime').timedelta(minutes=15)).isoformat(timespec="seconds")
        count=db.execute("SELECT COUNT(*) c FROM login_attempts WHERE key=? AND created_at>=?",(key,cutoff)).fetchone()["c"]
        if count>=8:
            error("Demasiadas tentativas. Volta a tentar dentro de 15 minutos.",429)
        row=db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if not row or not check_password(row["password_hash"],data.password):
            db.execute("INSERT INTO login_attempts(key,created_at) VALUES(?,?)",(key,now()))
            # commit failed-attempt count before raising
            failed=True
        else:
            failed=False
            db.execute("DELETE FROM login_attempts WHERE key=?",(key,))
            if row["status"] == "REJECTED":
                error("Conta indisponível. Contacta a administração.",403)
            csrf=issue_session(db,row["id"],response)
            audit(db,row["id"],"LOGIN","session",row["id"])
    if failed:
        error("Email ou palavra-passe incorretos",401)
    return {"ok":True,"csrf":csrf}

@router.get("/me")
def me(request:Request):
    u=auth(request,allow_pending=True,allow_suspended=True)
    return {"id":u["id"],"email":u["email"],"username":u["username"],"role":u["role"],"status":u["status"],
            "ff_uid":u["ff_uid"],"bio":u["bio"],"privacy_public":bool(u["privacy_public"]),"csrf":u["csrf_token"],"created_at":u["created_at"]}

@router.post("/logout")
def logout(request:Request,response:Response):
    u=auth(request,allow_pending=True,allow_suspended=True)
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?",(digest(request.cookies["fb_session"]),))
        audit(db,u["id"],"LOGOUT","session",u["id"])
    response.delete_cookie("fb_session",path="/")
    return {"ok":True}

@router.post("/logout-all")
def logout_all(request:Request,response:Response):
    u=auth(request,allow_pending=True,allow_suspended=True)
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE user_id=?",(u["id"],))
        audit(db,u["id"],"LOGOUT_ALL","session",u["id"])
    response.delete_cookie("fb_session",path="/")
    return {"ok":True}

@router.post("/change-password")
def change_password(data:ChangePassword,request:Request,response:Response):
    u=auth(request,allow_pending=True,allow_suspended=True)
    with transaction(immediate=True) as db:
        original=db.execute("SELECT password_hash FROM users WHERE id=?",(u["id"],)).fetchone()
        if not check_password(original["password_hash"],data.old_password):
            error("Palavra-passe atual incorreta",403)
        db.execute("UPDATE users SET password_hash=? WHERE id=?",(hash_password(data.new_password),u["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?",(u["id"],))
        audit(db,u["id"],"CHANGE_PASSWORD","user",u["id"])
    response.delete_cookie("fb_session",path="/")
    return {"ok":True,"message":"Palavra-passe alterada. Inicia sessão novamente."}


def send_reset_email(email,raw):
    host=os.getenv("FENRIR_SMTP_HOST")
    sender=os.getenv("FENRIR_SMTP_SENDER")
    if not host or not sender:
        return False
    msg=EmailMessage()
    msg["Subject"]="FENRIRBLOOD — Recuperação de palavra-passe"
    msg["From"]=sender
    msg["To"]=email
    msg.set_content(f"Se pediste a recuperação, abre este endereço (válido 20 minutos):\n{config.PUBLIC_URL}/?reset={raw}\nIgnora caso não tenhas pedido.")
    with smtplib.SMTP(host,int(os.getenv("FENRIR_SMTP_PORT","587")),timeout=12) as smtp:
        smtp.starttls()
        smtp.login(os.environ["FENRIR_SMTP_USER"],os.environ["FENRIR_SMTP_PASSWORD"])
        smtp.send_message(msg)
    return True

@router.get("/recovery-available")
def recovery_available():
    return {"available":bool(os.getenv("FENRIR_SMTP_HOST") and os.getenv("FENRIR_SMTP_SENDER"))}

@router.post("/recover")
def recover(data:Recover,request:Request):
    require_origin(request)
    if not os.getenv("FENRIR_SMTP_HOST") or not os.getenv("FENRIR_SMTP_SENDER"):
        error("Recuperação por email ainda não configurada. Contacta a administração.",503)
    public_rate_limit(request,"recovery",6,20)
    email=normalize_email(data.email)
    account=one("SELECT id FROM users WHERE email=?",(email,))
    if account:
        raw=token()
        with transaction() as db:
            db.execute("INSERT INTO reset_tokens(token_hash,user_id,expires_at) VALUES(?,?,?)",
                       (digest(raw),account["id"],future(minutes=20)))
        try:
            send_reset_email(email,raw)
        except Exception:
            error("Serviço de email temporariamente indisponível",503)
    return {"ok":True,"message":"Se a conta existir, receberás instruções por email."}

@router.post("/reset-password")
def reset_password(data:ResetPassword,request:Request,response:Response):
    require_origin(request)
    with transaction(immediate=True) as db:
        record=db.execute("SELECT user_id FROM reset_tokens WHERE token_hash=? AND expires_at > ? AND consumed_at IS NULL",
                          (digest(data.token),now())).fetchone()
        if not record:
            error("Ligação inválida ou expirada",400)
        db.execute("UPDATE users SET password_hash=? WHERE id=?",(hash_password(data.password),record["user_id"]))
        db.execute("UPDATE reset_tokens SET consumed_at=? WHERE token_hash=?",(now(),digest(data.token)))
        db.execute("DELETE FROM sessions WHERE user_id=?",(record["user_id"],))
        audit(db,record["user_id"],"RESET_PASSWORD","user",record["user_id"])
    response.delete_cookie("fb_session",path="/")
    return {"ok":True}
