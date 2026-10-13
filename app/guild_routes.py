import sqlite3
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from .core import auth,error,audit,notify,assert_active,check_length,OPERATIONS,MEMBER_ADMINS,LEADERS,ADMINS
from .db import one,rows,transaction
from .security import uid,now,week_start

router=APIRouter(prefix="/api", tags=["guild"])

class Profile(BaseModel):
    username:str=Field(min_length=2,max_length=40)
    ff_uid:str=Field(default="",max_length=30)
    bio:str=Field(default="",max_length=300)
    privacy_public:bool=True

class TeamCreate(BaseModel):
    name:str=Field(min_length=2,max_length=50)

class TeamMember(BaseModel):
    user_id:str

class TeamCaptain(BaseModel):
    user_id:str

class WarCreate(BaseModel):
    title:str=Field(min_length=2,max_length=100)
    opponent:str=Field(min_length=2,max_length=100)
    starts_at:str
    notes:str=Field(default="",max_length=1000)

class WarUpdate(BaseModel):
    status:str
    result:str=Field(default="",max_length=100)

class Score(BaseModel):
    user_id:str
    points:int=Field(ge=-100000,le=100000)
    reason:str=Field(min_length=5,max_length=500)
    week_start:str|None=None

class Event(BaseModel):
    title:str=Field(min_length=2,max_length=100)
    details:str=Field(default="",max_length=1000)
    starts_at:str


def iso_date(value):
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        if d.tzinfo is None:
            error("Indica a data e hora com fuso horário")
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        error("Data inválida")

@router.get("/dashboard")
def dashboard(request:Request):
    current=auth(request)
    online_threshold=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec="seconds")
    wk=week_start()
    member_stats=one("""SELECT COUNT(*) AS total,
                 SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS active,
                 SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending,
                 SUM(CASE WHEN status='ACTIVE' AND last_seen>=? THEN 1 ELSE 0 END) AS online
                 FROM users""",(online_threshold,))
    teams=one("SELECT COUNT(*) AS total, SUM(CASE WHEN count_members < 4 THEN 1 ELSE 0 END) AS incomplete FROM (SELECT t.id,COUNT(tm.user_id) count_members FROM teams t LEFT JOIN team_members tm ON tm.team_id=t.id GROUP BY t.id)")
    wars=rows("SELECT id,title,opponent,starts_at,status FROM wars WHERE status IN ('PLANNED','LIVE') ORDER BY starts_at LIMIT 5")
    events=rows("SELECT id,title,starts_at FROM events WHERE starts_at>=? ORDER BY starts_at LIMIT 5",(now(),))
    ranking=rows("""SELECT u.username,u.id,COALESCE(SUM(e.points),0) AS points FROM ranking_entries e JOIN users u ON u.id=e.user_id
                    WHERE e.week_start=? GROUP BY u.id ORDER BY points DESC LIMIT 5""",(wk,))
    recent=rows("SELECT a.action,a.created_at,u.username FROM audit_log a LEFT JOIN users u ON a.actor_id=u.id ORDER BY a.created_at DESC LIMIT 8") if current["role"] in ADMINS else []
    return {"members":member_stats,"teams":{"total":teams["total"] if teams else 0,"incomplete":teams["incomplete"] or 0 if teams else 0},
            "wars":wars,"events":events,"ranking":ranking,"week_start":wk,"activity":recent}

@router.get("/members")
def members(request:Request,q:str=""):
    actor=auth(request)
    q=q[:60].strip()
    if q:
        data=rows("""SELECT id,username,ff_uid,role,status,created_at,last_seen,bio,privacy_public FROM users
                      WHERE username LIKE ? OR ff_uid LIKE ? ORDER BY created_at DESC LIMIT 150""",('%'+q+'%','%'+q+'%'))
    else:
        data=rows("SELECT id,username,ff_uid,role,status,created_at,last_seen,bio,privacy_public FROM users ORDER BY created_at DESC LIMIT 150")
    if actor["role"] not in ADMINS:
        data=[u for u in data if u["status"]=="ACTIVE" and (u["privacy_public"] or actor["id"]==u["id"])]
    return {"members":data}

@router.get("/members/{member_id}")
def member_detail(member_id:str,request:Request):
    actor=auth(request)
    u=one("SELECT id,username,ff_uid,role,status,bio,privacy_public,created_at,last_seen FROM users WHERE id=?",(member_id,))
    if not u or (actor["role"] not in MEMBER_ADMINS and (u["status"]!="ACTIVE" or (not u["privacy_public"] and u["id"]!=actor["id"]))):
        error("Perfil indisponível",404)
    team=one("SELECT t.id,t.name FROM teams t JOIN team_members tm ON tm.team_id=t.id WHERE tm.user_id=?",(member_id,))
    u["team"]=team
    u["weekly_points"]=one("SELECT COALESCE(SUM(points),0) AS points FROM ranking_entries WHERE user_id=? AND week_start=?",(member_id,week_start()))["points"]
    u["war_confirmations"]=one("SELECT COUNT(*) AS count FROM war_lineups WHERE user_id=? AND confirmed=1",(member_id,))["count"]
    u["awards"]=rows("SELECT title,awarded_at FROM hall_awards WHERE member_id=? ORDER BY awarded_at DESC LIMIT 10",(member_id,))
    return u

@router.patch("/profile")
def profile(data:Profile,request:Request):
    actor=auth(request)
    username=check_length(data.username,2,40,"Nome de jogador")
    with transaction() as db:
        db.execute("UPDATE users SET username=?,ff_uid=?,bio=?,privacy_public=? WHERE id=?",
                   (username,data.ff_uid.strip(),data.bio.strip(),int(data.privacy_public),actor["id"]))
        audit(db,actor["id"],"EDIT_PROFILE","user",actor["id"])
    return {"ok":True}

@router.get("/teams")
def teams(request:Request):
    auth(request)
    ts=rows("""SELECT t.*,u.username captain_name FROM teams t LEFT JOIN users u ON t.captain_id=u.id ORDER BY t.name""")
    memberships=rows("""SELECT tm.team_id,tm.user_id,u.username,u.role,tm.joined_at FROM team_members tm JOIN users u ON tm.user_id=u.id ORDER BY tm.joined_at""")
    for t in ts:
        t["members"]=[m for m in memberships if m["team_id"]==t["id"]]
    reserves=rows("""SELECT u.id,u.username,u.role FROM users u LEFT JOIN team_members tm ON tm.user_id=u.id
                    WHERE tm.user_id IS NULL AND u.status='ACTIVE' ORDER BY u.username""")
    return {"teams":ts,"reserve":reserves}

@router.post("/teams")
def create_team(data:TeamCreate,request:Request):
    actor=auth(request,roles=OPERATIONS)
    tid=uid()
    try:
        with transaction(immediate=True) as db:
            db.execute("INSERT INTO teams(id,name,created_at,adaptation_end_at) VALUES(?,?,?,?)",
                       (tid,data.name.strip(),now(),(datetime.now(timezone.utc)+timedelta(days=14)).isoformat(timespec="seconds")))
            audit(db,actor["id"],"CREATE_TEAM","team",tid,{"name":data.name})
    except sqlite3.IntegrityError:
        error("Já existe uma equipa com este nome",409)
    return {"id":tid}

@router.post("/teams/{team_id}/members")
def assign_team(team_id:str,data:TeamMember,request:Request):
    actor=auth(request,roles=OPERATIONS|{"CAPITAO"})
    with transaction(immediate=True) as db:
        team=db.execute("SELECT * FROM teams WHERE id=?",(team_id,)).fetchone()
        if not team:
            error("Equipa inexistente",404)
        if actor["role"]=="CAPITAO" and team["captain_id"]!=actor["id"]:
            error("Só podes alterar a tua própria equipa",403)
        assert_active(db,data.user_id)
        current=db.execute("SELECT team_id FROM team_members WHERE user_id=?",(data.user_id,)).fetchone()
        if current and current["team_id"]==team_id:
            return {"ok":True,"already_assigned":True}
        if current and actor["role"]=="CAPITAO":
            error("Transferências entre equipas exigem autorização operacional",403)
        size=db.execute("SELECT COUNT(*) AS c FROM team_members WHERE team_id=?",(team_id,)).fetchone()["c"]
        if size>=4:
            error("Limite de quatro jogadores atingido",409)
        if current:
            old=db.execute("SELECT captain_id FROM teams WHERE id=?",(current["team_id"],)).fetchone()
            if old and old["captain_id"]==data.user_id:
                db.execute("UPDATE teams SET captain_id=NULL WHERE id=?",(current["team_id"],))
                db.execute("UPDATE users SET role='MEMBRO' WHERE id=? AND role='CAPITAO'",(data.user_id,))
            db.execute("DELETE FROM team_members WHERE user_id=?",(data.user_id,))
        db.execute("INSERT INTO team_members(team_id,user_id,joined_at) VALUES(?,?,?)",(team_id,data.user_id,now()))
        audit(db,actor["id"],"ASSIGN_TEAM","team",team_id,{"user_id":data.user_id,"from":current["team_id"] if current else None})
        notify(db,data.user_id,"team","Foste colocado/a numa nova equipa.")
    return {"ok":True}

@router.delete("/teams/{team_id}/members/{user_id}")
def remove_team_member(team_id:str,user_id:str,request:Request):
    actor=auth(request,roles=OPERATIONS|{"CAPITAO"})
    with transaction(immediate=True) as db:
        team=db.execute("SELECT captain_id FROM teams WHERE id=?",(team_id,)).fetchone()
        if not team:
            error("Equipa inexistente",404)
        if actor["role"]=="CAPITAO" and team["captain_id"]!=actor["id"]:
            error("Permissões insuficientes",403)
        db.execute("DELETE FROM team_members WHERE team_id=? AND user_id=?",(team_id,user_id))
        if team["captain_id"]==user_id:
            db.execute("UPDATE teams SET captain_id=NULL WHERE id=?",(team_id,))
            db.execute("UPDATE users SET role='MEMBRO' WHERE id=? AND role='CAPITAO'",(user_id,))
        audit(db,actor["id"],"REMOVE_TEAM_MEMBER","team",team_id,{"user_id":user_id})
    return {"ok":True}

@router.post("/teams/{team_id}/captain")
def choose_captain(team_id:str,data:TeamCaptain,request:Request):
    actor=auth(request,roles=OPERATIONS)
    with transaction(immediate=True) as db:
        if not db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",(team_id,data.user_id)).fetchone():
            error("O capitão deve pertencer à equipa",409)
        previous=db.execute("SELECT captain_id FROM teams WHERE id=?",(team_id,)).fetchone()
        db.execute("UPDATE teams SET captain_id=? WHERE id=?",(data.user_id,team_id))
        if previous and previous["captain_id"] and previous["captain_id"]!=data.user_id:
            db.execute("UPDATE users SET role='MEMBRO' WHERE id=? AND role='CAPITAO'",(previous["captain_id"],))
        db.execute("UPDATE users SET role='CAPITAO' WHERE id=? AND role='MEMBRO'",(data.user_id,))
        audit(db,actor["id"],"SET_CAPTAIN","team",team_id,{"user_id":data.user_id})
    return {"ok":True}

@router.post("/teams/{team_id}/extend")
def extend_team(team_id:str,request:Request):
    actor=auth(request,roles=OPERATIONS)
    with transaction(immediate=True) as db:
        team=db.execute("SELECT adaptation_end_at,extension_used FROM teams WHERE id=?",(team_id,)).fetchone()
        if not team: error("Equipa inexistente",404)
        if team["extension_used"]: error("A extensão de 7 dias já foi usada",409)
        end=datetime.fromisoformat(team["adaptation_end_at"])
        db.execute("UPDATE teams SET extension_used=1,adaptation_end_at=? WHERE id=?",
                   ((end+timedelta(days=7)).isoformat(timespec="seconds"),team_id))
        audit(db,actor["id"],"EXTEND_ADAPTATION","team",team_id)
    return {"ok":True}

@router.get("/wars")
def list_wars(request:Request):
    auth(request)
    return {"wars":rows("""SELECT w.*,u.username creator FROM wars w JOIN users u ON u.id=w.created_by ORDER BY w.starts_at DESC LIMIT 120""")}

@router.post("/wars")
def create_war(data:WarCreate,request:Request):
    actor=auth(request,roles=OPERATIONS)
    wid=uid()
    with transaction() as db:
        db.execute("INSERT INTO wars(id,title,opponent,starts_at,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                   (wid,data.title.strip(),data.opponent.strip(),iso_date(data.starts_at),data.notes.strip(),actor["id"],now()))
        audit(db,actor["id"],"CREATE_WAR","war",wid)
    return {"id":wid}

@router.post("/wars/{war_id}/status")
def update_war(war_id:str,data:WarUpdate,request:Request):
    actor=auth(request,roles=OPERATIONS)
    if data.status not in ("PLANNED","LIVE","DONE","CANCELLED"):
        error("Estado inválido")
    with transaction() as db:
        changed=db.execute("UPDATE wars SET status=?,result=? WHERE id=?",(data.status,data.result.strip(),war_id)).rowcount
        if not changed: error("Guerra inexistente",404)
        audit(db,actor["id"],"UPDATE_WAR","war",war_id,{"status":data.status,"result":data.result})
    return {"ok":True}

@router.post("/wars/{war_id}/lineup")
def war_lineup(war_id:str,data:TeamMember,request:Request):
    actor=auth(request,roles=OPERATIONS)
    with transaction(immediate=True) as db:
        if not db.execute("SELECT id FROM wars WHERE id=?",(war_id,)).fetchone():error("Guerra inexistente",404)
        assert_active(db,data.user_id)
        db.execute("INSERT OR IGNORE INTO war_lineups(war_id,user_id) VALUES(?,?)",(war_id,data.user_id))
        notify(db,data.user_id,"war","Foste convocado/a para uma guerra.")
        audit(db,actor["id"],"WAR_CALLUP","war",war_id,{"member":data.user_id})
    return {"ok":True}

@router.get("/wars/{war_id}/lineup")
def get_lineup(war_id:str,request:Request):
    auth(request)
    return {"lineup":rows("SELECT l.user_id,l.confirmed,u.username FROM war_lineups l JOIN users u ON l.user_id=u.id WHERE l.war_id=?",(war_id,))}

@router.post("/wars/{war_id}/confirm")
def confirm_war(war_id:str,request:Request):
    actor=auth(request)
    with transaction() as db:
        updated=db.execute("UPDATE war_lineups SET confirmed=1 WHERE war_id=? AND user_id=?",(war_id,actor["id"])).rowcount
        if not updated: error("Não estás convocado/a",403)
        audit(db,actor["id"],"CONFIRM_WAR","war",war_id)
    return {"ok":True}

@router.get("/ranking")
def ranking(request:Request,week:str|None=None):
    auth(request)
    wk=week or week_start()
    try:datetime.strptime(wk,"%Y-%m-%d")
    except ValueError:error("Semana inválida")
    if datetime.strptime(wk,"%Y-%m-%d").weekday()!=0:error("A semana deve começar na segunda-feira")
    data=rows("""SELECT u.id,u.username,u.role,SUM(r.points) points FROM ranking_entries r
                 JOIN users u ON u.id=r.user_id WHERE r.week_start=? GROUP BY u.id
                 ORDER BY points DESC,u.username LIMIT 200""",(wk,))
    return {"week_start":wk,"ranking":data}

@router.post("/ranking/entries")
def add_score(data:Score,request:Request):
    actor=auth(request,roles=OPERATIONS)
    wk=data.week_start or week_start()
    try:d=datetime.strptime(wk,"%Y-%m-%d")
    except ValueError:error("Semana inválida")
    if d.weekday()!=0:error("A semana deve começar na segunda-feira")
    if not data.points:error("A pontuação não pode ser zero")
    record_id=uid()
    with transaction(immediate=True) as db:
        assert_active(db,data.user_id)
        if db.execute("SELECT 1 FROM ranking_finalizations WHERE week_start=?",(wk,)).fetchone():
            error("Ranking já validado pelos fundadores; não admite correções",409)
        db.execute("INSERT INTO ranking_entries(id,user_id,week_start,points,reason,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                   (record_id,data.user_id,wk,data.points,data.reason.strip(),actor["id"],now()))
        audit(db,actor["id"],"SCORE_ADJUSTMENT","ranking",record_id,{"user":data.user_id,"points":data.points,"week":wk})
        notify(db,data.user_id,"ranking",f"Pontuação ajustada em {data.points:+d} pontos.")
    return {"id":record_id}

@router.get("/events")
def events(request:Request):
    auth(request)
    return {"events":rows("SELECT e.*,u.username creator FROM events e JOIN users u ON e.created_by=u.id ORDER BY starts_at DESC LIMIT 120")}

@router.post("/events")
def new_event(data:Event,request:Request):
    actor=auth(request,roles=LEADERS)
    eid=uid()
    with transaction() as db:
        db.execute("INSERT INTO events(id,title,details,starts_at,created_by,created_at) VALUES(?,?,?,?,?,?)",
                   (eid,data.title.strip(),data.details.strip(),iso_date(data.starts_at),actor["id"],now()))
        audit(db,actor["id"],"CREATE_EVENT","event",eid)
    return {"id":eid}
