import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import pytest
from fastapi.testclient import TestClient
from app import config
from app.db import one,rows,initialize
from scripts.bootstrap_founders import bootstrap
from app.main import app

@pytest.fixture()
def env(tmp_path,monkeypatch):
    monkeypatch.setattr(config,"DB_PATH",tmp_path / "fenrir.sqlite3")
    monkeypatch.setattr(config,"PUBLIC_URL","http://testserver")
    monkeypatch.setattr(config,"SECURE_COOKIES",False)
    initialize()
    bootstrap([("alpha@example.com","AlphaFounder","supersecretalpha_123"),("beta@example.com","BetaFounder","supersecretbeta_123")])
    with TestClient(app) as client:
        yield client


def call(c,method,url,json=None):
    headers={}
    if method not in ("GET",):
        me=c.get("/api/auth/me")
        if me.status_code==200:headers["X-CSRF-Token"]=me.json()["csrf"]
    return c.request(method,url,json=json,headers=headers)


def login(c,email,password):
    r=c.post("/api/auth/login",json={"email":email,"password":password})
    assert r.status_code==200,r.text
    return r.json()


def register(c,n):
    r=c.post("/api/auth/register",json={"email":f"m{n}@example.com","username":f"Membro{n}","password":"membro_password1234"})
    assert r.status_code==200,r.text
    return one("SELECT id FROM users WHERE email=?",(f"m{n}@example.com",))["id"]


def approve(c,id):
    return call(c,"POST",f"/api/admin/pending/{id}/approve")


def member_client(env,n):
    member_id=register(env,n)
    login(env,"alpha@example.com","supersecretalpha_123")
    r=approve(env,member_id)
    assert r.status_code==200,r.text
    member=TestClient(app)
    login(member,f"m{n}@example.com","membro_password1234")
    return member,member_id


def test_registration_pending_gate(env):
    user_id=register(env,1)
    login(env,"m1@example.com","membro_password1234")
    assert env.get("/api/auth/me").json()["status"]=="PENDING"
    assert env.get("/api/teams").status_code==403
    login(env,"alpha@example.com","supersecretalpha_123")
    assert approve(env,user_id).status_code==200
    assert approve(env,user_id).status_code==409
    login(env,"m1@example.com","membro_password1234")
    assert env.get("/api/dashboard").status_code==200


def test_member_cannot_admin_or_spoof_csrf(env):
    m,mid=member_client(env,2)
    assert m.get("/api/admin/pending").status_code==403
    assert call(m,"POST","/api/teams",{"name":"Proibida"}).status_code==403
    assert m.post("/api/feed",json={"body":"Sem CSRF"}).status_code==403
    assert call(m,"POST","/api/feed",{"body":"Publicação real"}).status_code==200
    assert m.get("/api/feed").json()["posts"][0]["body"]=="Publicação real"
    m.close()


def test_team_capacity_and_transfer(env):
    ids=[register(env,i) for i in range(10,15)]
    login(env,"alpha@example.com","supersecretalpha_123")
    for x in ids: assert approve(env,x).status_code==200
    team_id=call(env,"POST","/api/teams",{"name":"Alcateia Alpha"}).json()["id"]
    for x in ids[:4]:assert call(env,"POST",f"/api/teams/{team_id}/members",{"user_id":x}).status_code==200
    assert call(env,"POST",f"/api/teams/{team_id}/members",{"user_id":ids[4]}).status_code==409
    assert len(env.get("/api/teams").json()["teams"][0]["members"])==4
    assert call(env,"DELETE",f"/api/teams/{team_id}/members/{ids[0]}").status_code==200
    assert call(env,"POST",f"/api/teams/{team_id}/members",{"user_id":ids[4]}).status_code==200


def test_founder_dual_approval_is_real(env):
    m,mid=member_client(env,20)
    login(env,"alpha@example.com","supersecretalpha_123")
    proposal=call(env,"POST","/api/admin/proposals",{"action":"SET_ROLE","target_user_id":mid,"role":"ADMIN_OPERACIONAL"})
    assert proposal.status_code==200,proposal.text
    pid=proposal.json()["id"]
    assert call(env,"POST",f"/api/admin/proposals/{pid}/approve").status_code==409
    assert one("SELECT role FROM users WHERE id=?",(mid,))["role"]=="MEMBRO"
    second=TestClient(app)
    login(second,"beta@example.com","supersecretbeta_123")
    assert call(second,"POST",f"/api/admin/proposals/{pid}/approve").json()["executed"] is True
    assert call(second,"POST",f"/api/admin/proposals/{pid}/approve").status_code==409
    assert one("SELECT role FROM users WHERE id=?",(mid,))["role"]=="ADMIN_OPERACIONAL"
    second.close();m.close()


def test_private_message_is_private(env):
    a,aid=member_client(env,31)
    b,bid=member_client(env,32)
    c,cid=member_client(env,33)
    assert call(a,"POST","/api/messages",{"body":"Mensagem secreta","channel":"private","target_id":bid}).status_code==200
    received=b.get(f"/api/messages?channel=private&target_id={aid}").json()["messages"]
    assert len(received)==1 and received[0]["body"]=="Mensagem secreta"
    assert c.get(f"/api/messages?channel=private&target_id={aid}").json()["messages"]==[]
    assert c.get("/api/messages?channel=admin").status_code==403
    for x in (a,b,c):x.close()


def test_wars_scores_sessions(env):
    m,mid=member_client(env,40)
    login(env,"alpha@example.com","supersecretalpha_123")
    now=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    w=call(env,"POST","/api/wars",{"title":"Jogo 1","opponent":"Rivais","starts_at":now}).json()["id"]
    assert call(env,"POST",f"/api/wars/{w}/lineup",{"user_id":mid}).status_code==200
    assert call(m,"POST",f"/api/wars/{w}/confirm").status_code==200
    assert call(env,"POST","/api/ranking/entries",{"user_id":mid,"points":250,"reason":"Pontuação verificada"}).status_code==200
    assert any(x["id"]==mid and x["points"]==250 for x in m.get("/api/ranking").json()["ranking"])
    assert call(m,"POST","/api/auth/logout").status_code==200
    assert m.get("/api/dashboard").status_code==401
    m.close()


def test_appeal_flow(env):
    m,mid=member_client(env,45)
    login(env,"alpha@example.com","supersecretalpha_123")
    p=call(env,"POST","/api/admin/proposals",{"action":"SUSPEND","target_user_id":mid,"days":2,"serious":True,"reason":"Infração grave documentada e verificada"}).json()["id"]
    second=TestClient(app); login(second,"beta@example.com","supersecretbeta_123")
    assert call(second,"POST",f"/api/admin/proposals/{p}/approve").status_code==200
    assert m.get("/api/dashboard").status_code==401
    login(m,"m45@example.com","membro_password1234")
    assert m.get("/api/auth/me").json()["status"]=="SUSPENDED"
    assert m.get("/api/dashboard").status_code==403
    assert call(m,"POST","/api/admin/appeal",{"reason":"Solicito revisão da decisão"}).status_code==200
    second.close();m.close()


def test_media_upload_and_gallery_are_protected(env):
    from io import BytesIO
    from PIL import Image
    m,mid=member_client(env,51)
    b=BytesIO()
    Image.new("RGB",(32,32),(120,32,40)).save(b,format="PNG")
    tok=m.get("/api/auth/me").json()["csrf"]
    rsp=m.post("/api/media",files={"file":("sample.png",b.getvalue(),"image/png")},headers={"X-CSRF-Token":tok})
    assert rsp.status_code==200,rsp.text
    media=rsp.json()
    assert m.get(media["url"]).status_code==200
    x=call(m,"POST","/api/feed",{"body":"Foto real do treino","media_ids":[media["id"]]})
    assert x.status_code==200,x.text
    posts=m.get("/api/feed").json()["posts"]
    assert posts[0]["images"]==[media["url"]]
    stranger=TestClient(app)
    assert stranger.get(media["url"]).status_code==401
    stranger.close();m.close()


def test_hall_and_rule_based_intelligence(env):
    m,mid=member_client(env,52)
    assert m.get("/api/intelligence").status_code==403
    login(env,"alpha@example.com","supersecretalpha_123")
    r=call(env,"POST","/api/hall/awards",{"member_id":mid,"title":"Destaque da semana","description":"Atividade e trabalho em equipa"})
    assert r.status_code==200,r.text
    assert any(x["title"]=="Destaque da semana" for x in m.get("/api/hall").json()["awards"])
    intelligence=env.get("/api/intelligence")
    assert intelligence.status_code==200
    assert intelligence.json()["ai_status"]=="unavailable"
    assert intelligence.json()["reserve_members"]
    m.close()


def test_concurrent_team_assignments_never_exceed_four(env):
    ids=[register(env,i) for i in range(60,66)]
    login(env,"alpha@example.com","supersecretalpha_123")
    for i in ids:assert approve(env,i).status_code==200
    tid=call(env,"POST","/api/teams",{"name":"Escalão Paralelo"}).json()["id"]
    csrf=env.get("/api/auth/me").json()["csrf"]
    cookie=env.cookies.get("fb_session")
    def assign(member_id):
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            c.cookies.set("fb_session",cookie)
            return c.post(f"/api/teams/{tid}/members",json={"user_id":member_id},headers={"X-CSRF-Token":csrf}).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes=list(pool.map(assign,ids))
    assert codes.count(200)==4,codes
    assert codes.count(409)==2,codes
    assert one("SELECT COUNT(*) n FROM team_members WHERE team_id=?",(tid,))["n"]==4


def test_finalized_week_rejects_later_scores(env):
    m,mid=member_client(env,70)
    login(env,"alpha@example.com","supersecretalpha_123")
    wk=env.get("/api/ranking").json()["week_start"]
    p=call(env,"POST","/api/admin/proposals",{"action":"FINALIZE_WEEK","week_start":wk}).json()["id"]
    second=TestClient(app);login(second,"beta@example.com","supersecretbeta_123")
    assert call(second,"POST",f"/api/admin/proposals/{p}/approve").status_code==200
    r=call(env,"POST","/api/ranking/entries",{"user_id":mid,"points":10,"reason":"Após validação","week_start":wk})
    assert r.status_code==409
    second.close();m.close()
