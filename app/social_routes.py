from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from .core import auth,error,audit,notify,ADMINS,OPERATIONS
from .db import rows,one,transaction
from .security import uid,now

router=APIRouter(prefix="/api",tags=["social"])

class Body(BaseModel):
    body:str=Field(min_length=1,max_length=3000)
    media_ids:list[str]=Field(default_factory=list,max_length=4)

class Comment(Body):
    parent_id:str|None=None

class Message(Body):
    channel:str="general"
    target_id:str=""

@router.get("/feed")
def feed(request:Request,offset:int=0):
    u=auth(request)
    offset=max(0,min(offset,10000))
    posts=rows("""SELECT p.id,p.body,p.pinned,p.created_at,p.updated_at,p.author_id,u.username author,
                  (SELECT COUNT(*) FROM reactions r WHERE r.post_id=p.id) AS likes,
                  (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments,
                  EXISTS(SELECT 1 FROM reactions r2 WHERE r2.post_id=p.id AND r2.user_id=?) liked
                  FROM posts p JOIN users u ON p.author_id=u.id
                  WHERE p.hidden=0 ORDER BY p.pinned DESC,p.created_at DESC LIMIT 30 OFFSET ?""",(u["id"],offset))
    if posts:
        ph=",".join("?" for _ in posts)
        ids=[p["id"] for p in posts]
        files=rows(f"SELECT post_id,media_id FROM post_media WHERE post_id IN ({ph}) ORDER BY position",ids)
        for item in posts:
            item["images"]=[f"/api/media/{x['media_id']}" for x in files if x["post_id"]==item["id"]]
    return {"posts":posts,"offset":offset,"has_more":len(posts)==30}

@router.post("/feed")
def post(data:Body,request:Request):
    u=auth(request)
    pid=uid()
    with transaction() as db:
        db.execute("INSERT INTO posts(id,author_id,body,created_at) VALUES(?,?,?,?)",(pid,u["id"],data.body.strip(),now()))
        for position,mid in enumerate(data.media_ids):
            record=db.execute("SELECT id FROM media WHERE id=? AND uploader_id=?",(mid,u["id"])).fetchone()
            if not record:error("Imagem inexistente ou não autorizada",403)
            if db.execute("SELECT 1 FROM post_media WHERE media_id=?",(mid,)).fetchone():
                error("Imagem já utilizada",409)
            db.execute("INSERT INTO post_media(post_id,media_id,position) VALUES(?,?,?)",(pid,mid,position))
        audit(db,u["id"],"CREATE_POST","post",pid)
    return {"id":pid}

@router.patch("/feed/{post_id}")
def edit_post(post_id:str,data:Body,request:Request):
    u=auth(request)
    with transaction() as db:
        p=db.execute("SELECT author_id FROM posts WHERE id=?",(post_id,)).fetchone()
        if not p:error("Publicação inexistente",404)
        if p["author_id"]!=u["id"] and u["role"] not in ADMINS:error("Sem permissão",403)
        db.execute("UPDATE posts SET body=?,updated_at=? WHERE id=?",(data.body.strip(),now(),post_id))
        audit(db,u["id"],"EDIT_POST","post",post_id)
    return {"ok":True}

@router.delete("/feed/{post_id}")
def delete_post(post_id:str,request:Request):
    u=auth(request)
    with transaction() as db:
        p=db.execute("SELECT author_id FROM posts WHERE id=?",(post_id,)).fetchone()
        if not p:error("Publicação inexistente",404)
        if p["author_id"]!=u["id"] and u["role"] not in ADMINS:error("Sem permissão",403)
        db.execute("UPDATE posts SET hidden=1 WHERE id=?",(post_id,))
        audit(db,u["id"],"MODERATE_POST","post",post_id)
    return {"ok":True}

@router.post("/feed/{post_id}/react")
def react(post_id:str,request:Request):
    u=auth(request)
    with transaction() as db:
        if not db.execute("SELECT 1 FROM posts WHERE id=? AND hidden=0",(post_id,)).fetchone():error("Publicação inexistente",404)
        changed=db.execute("DELETE FROM reactions WHERE post_id=? AND user_id=?",(post_id,u["id"])).rowcount
        if not changed:
            db.execute("INSERT INTO reactions(post_id,user_id) VALUES(?,?)",(post_id,u["id"]))
    return {"liked":not bool(changed)}

@router.get("/feed/{post_id}/comments")
def get_comments(post_id:str,request:Request):
    auth(request)
    return {"comments":rows("""SELECT c.*,u.username author FROM comments c JOIN users u ON u.id=c.author_id
                               WHERE post_id=? ORDER BY created_at LIMIT 150""",(post_id,))}

@router.post("/feed/{post_id}/comments")
def add_comment(post_id:str,data:Comment,request:Request):
    u=auth(request)
    cid=uid()
    with transaction() as db:
        p=db.execute("SELECT author_id FROM posts WHERE id=? AND hidden=0",(post_id,)).fetchone()
        if not p:error("Publicação inexistente",404)
        if data.parent_id and not db.execute("SELECT 1 FROM comments WHERE id=? AND post_id=?",(data.parent_id,post_id)).fetchone():
            error("Comentário anterior inexistente",404)
        db.execute("INSERT INTO comments(id,post_id,author_id,body,created_at,parent_id) VALUES(?,?,?,?,?,?)",
                   (cid,post_id,u["id"],data.body.strip(),now(),data.parent_id))
        if p["author_id"]!=u["id"]:notify(db,p["author_id"],"feed",f"{u['username']} comentou uma publicação tua.")
    return {"id":cid}


def authorize_channel(db,u,channel,target):
    if channel not in ("general","admin","team","war","private"):
        error("Canal inválido")
    if channel=="general":
        if target:error("Este canal não admite destino")
        return
    if channel=="admin":
        if u["role"] not in ADMINS:error("Canal reservado à administração",403)
        if target:error("Este canal não admite destino")
    if channel=="team":
        if not db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",(target,u["id"])).fetchone() and u["role"] not in OPERATIONS:
            error("Não pertences a esta equipa",403)
        if not db.execute("SELECT 1 FROM teams WHERE id=?",(target,)).fetchone():error("Equipa inexistente",404)
    if channel=="war":
        if not db.execute("SELECT 1 FROM war_lineups WHERE war_id=? AND user_id=?",(target,u["id"])).fetchone() and u["role"] not in OPERATIONS:
            error("Não participas nesta guerra",403)
        if not db.execute("SELECT 1 FROM wars WHERE id=?",(target,)).fetchone():error("Guerra inexistente",404)
    if channel=="private":
        if target==u["id"]:error("Seleciona outro membro")
        if not db.execute("SELECT 1 FROM users WHERE id=? AND status='ACTIVE'",(target,)).fetchone():error("Destinatário indisponível",404)

@router.get("/messages")
def messages(request:Request,channel:str="general",target_id:str="",before:str=""):
    u=auth(request)
    with transaction() as db:
        authorize_channel(db,u,channel,target_id)
        if channel=="private":
            data=db.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.username author
                   FROM messages m JOIN users u ON m.author_id=u.id WHERE m.channel='private'
                   AND ((m.author_id=? AND m.target_id=?) OR (m.author_id=? AND m.target_id=?))
                   AND m.created_at < ? ORDER BY m.created_at DESC LIMIT 100""",
                   (u["id"],target_id,target_id,u["id"],before or "9999-12-31")).fetchall()
        else:
            data=db.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.username author
                   FROM messages m JOIN users u ON m.author_id=u.id WHERE m.channel=? AND m.target_id=?
                   AND m.created_at < ? ORDER BY m.created_at DESC LIMIT 100""",
                   (channel,target_id,before or "9999-12-31")).fetchall()
    return {"messages":[dict(x) for x in reversed(data)]}

@router.post("/messages")
def send_message(data:Message,request:Request):
    u=auth(request)
    if len(data.body.strip())<1:error("Mensagem vazia")
    mid=uid()
    with transaction() as db:
        authorize_channel(db,u,data.channel,data.target_id)
        db.execute("INSERT INTO messages(id,author_id,channel,target_id,body,created_at) VALUES(?,?,?,?,?,?)",
                   (mid,u["id"],data.channel,data.target_id,data.body.strip(),now()))
        if data.channel=="private":notify(db,data.target_id,"message",f"Nova mensagem de {u['username']}.")
    return {"id":mid}

@router.get("/notifications")
def notifications(request:Request):
    u=auth(request)
    result=rows("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",(u["id"],))
    return {"notifications":result,"unread":sum(1 for x in result if not x["read_at"])}

@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id:str,request:Request):
    u=auth(request)
    with transaction() as db:
        result=db.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?",(now(),notification_id,u["id"]))
        if not result.rowcount:error("Notificação inexistente",404)
    return {"ok":True}
