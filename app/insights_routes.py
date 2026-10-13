from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request
from pydantic import BaseModel,Field
from .db import rows,one,transaction
from .core import auth,error,audit,notify,ADMINS,OPERATIONS
from .security import uid,now,week_start

router=APIRouter(prefix="/api",tags=["hall-intelligence"])

class Award(BaseModel):
    member_id:str
    title:str=Field(min_length=2,max_length=90)
    description:str=Field(default="",max_length=400)

@router.get("/hall")
def hall(request:Request):
    auth(request)
    awards=rows("""SELECT a.id,a.title,a.description,a.awarded_at,u.username member,u.id member_id,
                  issuer.username issuer FROM hall_awards a JOIN users u ON a.member_id=u.id
                  JOIN users issuer ON issuer.id=a.awarded_by ORDER BY a.awarded_at DESC LIMIT 150""")
    return {"awards":awards,"count":len(awards)}

@router.post("/hall/awards")
def grant_award(data:Award,request:Request):
    actor=auth(request,roles=ADMINS)
    aid=uid()
    with transaction() as db:
        member=db.execute("SELECT username FROM users WHERE id=? AND status='ACTIVE'",(data.member_id,)).fetchone()
        if not member:error("Membro não encontrado",404)
        db.execute("INSERT INTO hall_awards(id,member_id,title,description,awarded_by,awarded_at) VALUES(?,?,?,?,?,?)",
                   (aid,data.member_id,data.title.strip(),data.description.strip(),actor["id"],now()))
        audit(db,actor["id"],"AWARD_MEDAL","hall",aid,{"member_id":data.member_id,"title":data.title})
        notify(db,data.member_id,"hall",f"Recebeste uma nova conquista: {data.title}!")
    return {"id":aid}

@router.get("/intelligence")
def intelligence(request:Request):
    auth(request,roles=OPERATIONS)
    threshold=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec="seconds")
    unsquadded=rows("""SELECT u.id,u.username FROM users u LEFT JOIN team_members t ON t.user_id=u.id
                          WHERE u.status='ACTIVE' AND t.user_id IS NULL ORDER BY u.username LIMIT 50""")
    incomplete=rows("""SELECT t.id,t.name,COUNT(m.user_id) members FROM teams t
                          LEFT JOIN team_members m ON m.team_id=t.id GROUP BY t.id
                          HAVING COUNT(m.user_id)<4 ORDER BY members,t.name""")
    inactive=rows("""SELECT id,username,last_seen FROM users WHERE status='ACTIVE' AND role!='FUNDADOR'
                        AND (last_seen IS NULL OR last_seen<?) ORDER BY last_seen LIMIT 50""",(threshold,))
    planned=one("SELECT COUNT(*) as c FROM wars WHERE status='PLANNED'")
    pending=one("SELECT COUNT(*) as c FROM users WHERE status='PENDING'")
    insights=[]
    if incomplete: insights.append({"severity":"warning","title":"Esquadrões incompletos","detail":f"{len(incomplete)} equipa(s) com menos de quatro jogadores."})
    if inactive: insights.append({"severity":"warning","title":"Atividade por rever","detail":f"{len(inactive)} membro(s) sem atividade registada há pelo menos sete dias. Necessária revisão humana; nenhuma sanção automática."})
    if unsquadded: insights.append({"severity":"info","title":"Reserva geral","detail":f"{len(unsquadded)} membro(s) sem equipa fixa."})
    if pending["c"]: insights.append({"severity":"info","title":"Aprovações pendentes","detail":f"{pending['c']} candidatura(s) a aguardar decisão."})
    return {"ai_status":"unavailable","ai_reason":"Nenhum fornecedor externo de IA está configurado.",
            "rules_based_insights":insights,"incomplete_teams":incomplete,
            "inactive_members":inactive,"reserve_members":unsquadded,
            "planned_wars":planned["c"],"pending_members":pending["c"],"week_start":week_start()}
