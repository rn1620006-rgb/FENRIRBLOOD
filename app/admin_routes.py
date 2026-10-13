import json
from datetime import datetime,timedelta,timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from .core import auth,error,audit,notify,MEMBER_ADMINS,OPERATIONS,ADMINS
from .db import transaction,rows
from .security import uid,now

router=APIRouter(prefix="/api/admin",tags=["administration"])

class Reason(BaseModel):
    reason:str=Field(min_length=5,max_length=1000)

class Proposal(BaseModel):
    action:str
    target_user_id:str|None=None
    role:str|None=None
    days:int|None=None
    reason:str=Field(default="",max_length=1000)
    serious:bool=False
    week_start:str|None=None

@router.get("/pending")
def pending(request:Request):
    auth(request,roles=MEMBER_ADMINS)
    return {"members":rows("SELECT id,email,username,ff_uid,created_at FROM users WHERE status='PENDING' ORDER BY created_at LIMIT 150")}

@router.post("/pending/{user_id}/approve")
def approve_member(user_id:str,request:Request):
    u=auth(request,roles=MEMBER_ADMINS)
    with transaction(immediate=True) as db:
        result=db.execute("UPDATE users SET status='ACTIVE',role='MEMBRO',approved_at=? WHERE id=? AND status='PENDING' AND role='PENDENTE'",(now(),user_id))
        if not result.rowcount:error("Candidatura não encontrada ou já analisada",409)
        audit(db,u["id"],"APPROVE_MEMBER","user",user_id)
        notify(db,user_id,"account","A tua conta foi aprovada. Bem-vindo/a à Matilha!")
    return {"ok":True}

@router.post("/members/{user_id}/warning")
def warning(user_id:str,data:Reason,request:Request):
    u=auth(request,roles=MEMBER_ADMINS)
    wid=uid()
    with transaction(immediate=True) as db:
        target=db.execute("SELECT role,status FROM users WHERE id=?",(user_id,)).fetchone()
        if not target or target["status"] not in ("ACTIVE","SUSPENDED"):
            error("Membro inválido",404)
        if target["role"]=="FUNDADOR":error("Não é permitido advertir fundadores por esta via",403)
        db.execute("INSERT INTO discipline(id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,'WARNING',?,?)",
                   (wid,user_id,u["id"],data.reason.strip(),now()))
        audit(db,u["id"],"ISSUE_WARNING","user",user_id,{"reason":data.reason})
        notify(db,user_id,"discipline","Recebeste uma advertência. Consulta a administração.")
    return {"id":wid}

@router.get("/discipline")
def discipline(request:Request):
    auth(request,roles=MEMBER_ADMINS)
    return {"history":rows("""SELECT d.*,u.username member,a.username actor FROM discipline d
                   JOIN users u ON u.id=d.user_id JOIN users a ON a.id=d.actor_id
                   ORDER BY d.created_at DESC LIMIT 150""")}

@router.post("/appeal")
def appeal(data:Reason,request:Request):
    u=auth(request,allow_pending=True,allow_suspended=True)
    if u["status"]!="SUSPENDED":error("Apenas contas suspensas podem recorrer",403)
    did=uid()
    with transaction() as db:
        db.execute("INSERT INTO discipline(id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,'APPEAL',?,?)",
                   (did,u["id"],u["id"],data.reason.strip(),now()))
        for f in db.execute("SELECT id FROM users WHERE role='FUNDADOR' AND status='ACTIVE'").fetchall():
            notify(db,f["id"],"appeal",f"Recurso submetido por {u['username']}.")
        audit(db,u["id"],"FILE_APPEAL","user",u["id"])
    return {"id":did}

@router.get("/proposals")
def proposals(request:Request):
    auth(request,roles={"FUNDADOR"})
    result=rows("""SELECT p.id,p.action,p.payload,p.proposed_by,p.status,p.created_at,p.executed_at,
                  (SELECT COUNT(*) FROM approvals a WHERE a.proposal_id=p.id) approvals
                  FROM proposals p ORDER BY p.created_at DESC LIMIT 100""")
    for item in result:
        item["payload"]=json.loads(item["payload"])
    return {"proposals":result}


def validate_proposal(db, data):
    if data.action=="SET_ROLE":
        if data.role not in ("MEMBRO","CAPITAO","ADMIN_MEMBROS","ADMIN_OPERACIONAL"):
            error("Cargo não permitido")
        target=db.execute("SELECT role,status FROM users WHERE id=?",(data.target_user_id,)).fetchone()
        if not target or target["role"]=="FUNDADOR" or target["status"]!="ACTIVE":
            error("Membro inexistente ou não elegível",404)
    elif data.action in ("SUSPEND","REINSTATE"):
        target=db.execute("SELECT role,status FROM users WHERE id=?",(data.target_user_id,)).fetchone()
        if not target or target["role"]=="FUNDADOR":error("Conta não elegível",403)
        if data.action=="SUSPEND":
            if target["status"]!="ACTIVE":error("Conta não está ativa",409)
            if not data.days or not (1<=data.days<=30) or len(data.reason.strip())<10:
                error("Indica duração de 1 a 30 dias e justificação detalhada")
            strikes=db.execute("SELECT COUNT(*) c FROM discipline WHERE user_id=? AND action='WARNING'",(data.target_user_id,)).fetchone()["c"]
            if strikes<2 and not data.serious:
                error("São necessárias duas advertências, salvo infração grave expressamente justificada",409)
        elif target["status"]!="SUSPENDED":error("Conta não está suspensa",409)
    elif data.action=="FINALIZE_WEEK":
        wk=data.week_start
        try:
            day=datetime.strptime(wk,"%Y-%m-%d")
            if day.weekday()!=0:raise ValueError()
        except (TypeError,ValueError):error("A data deve ser uma segunda-feira válida")
        if db.execute("SELECT 1 FROM ranking_finalizations WHERE week_start=?",(wk,)).fetchone():
            error("Semana já validada",409)
    else:
        error("Operação estratégica não suportada")


def execute_proposal(db,proposal,approver):
    payload=json.loads(proposal["payload"])
    data=Proposal(**payload)
    validate_proposal(db,data)
    if data.action=="SET_ROLE":
        db.execute("UPDATE users SET role=? WHERE id=?",(data.role,data.target_user_id))
        notify(db,data.target_user_id,"role",f"O teu cargo foi alterado para {data.role}.")
    elif data.action=="SUSPEND":
        ends=(datetime.now(timezone.utc)+timedelta(days=data.days)).isoformat(timespec="seconds")
        db.execute("UPDATE users SET status='SUSPENDED' WHERE id=?",(data.target_user_id,))
        db.execute("DELETE FROM sessions WHERE user_id=?",(data.target_user_id,))
        # Member can log in again only to see suspension and submit a documented appeal.
        db.execute("INSERT INTO discipline(id,user_id,actor_id,action,reason,ends_at,created_at) VALUES(?,?,?,'SUSPENSION',?,?,?)",
                   (uid(),data.target_user_id,approver,data.reason,ends,now()))
        notify(db,data.target_user_id,"discipline","A tua conta foi suspensa. Podes apresentar recurso após iniciar sessão.")
    elif data.action=="REINSTATE":
        db.execute("UPDATE users SET status='ACTIVE' WHERE id=?",(data.target_user_id,))
        db.execute("INSERT INTO discipline(id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,'REINSTATEMENT',?,?)",
                   (uid(),data.target_user_id,approver,data.reason or "Reintegração aprovada",now()))
        notify(db,data.target_user_id,"discipline","A tua conta foi reintegrada.")
    elif data.action=="FINALIZE_WEEK":
        db.execute("INSERT INTO ranking_finalizations(week_start,proposal_id,finalized_at) VALUES(?,?,?)",
                   (data.week_start,proposal["id"],now()))
    db.execute("UPDATE proposals SET status='EXECUTED',executed_at=? WHERE id=?",(now(),proposal["id"]))
    audit(db,approver,"EXECUTE_DUAL_APPROVAL",data.action,proposal["id"],payload)

@router.post("/proposals")
def create_proposal(data:Proposal,request:Request):
    u=auth(request,roles={"FUNDADOR"})
    pid=uid()
    with transaction(immediate=True) as db:
        founders=db.execute("SELECT COUNT(*) c FROM users WHERE role='FUNDADOR' AND status='ACTIVE'").fetchone()["c"]
        if founders!=2:error("É obrigatório existirem dois fundadores ativos",409)
        validate_proposal(db,data)
        db.execute("INSERT INTO proposals(id,action,payload,proposed_by,created_at) VALUES(?,?,?,?,?)",
                   (pid,data.action,data.model_dump_json(),u["id"],now()))
        db.execute("INSERT INTO approvals(proposal_id,founder_id,approved_at) VALUES(?,?,?)",(pid,u["id"],now()))
        audit(db,u["id"],"PROPOSE_DUAL_APPROVAL",data.action,pid,data.model_dump())
        for founder in db.execute("SELECT id FROM users WHERE role='FUNDADOR' AND id<>?",(u["id"],)).fetchall():
            notify(db,founder["id"],"approval",f"Proposta {data.action} aguarda a tua aprovação.")
    return {"id":pid,"approvals":1,"status":"PENDING"}

@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id:str,request:Request):
    u=auth(request,roles={"FUNDADOR"})
    with transaction(immediate=True) as db:
        proposal=db.execute("SELECT * FROM proposals WHERE id=?",(proposal_id,)).fetchone()
        if not proposal:error("Proposta inexistente",404)
        if proposal["status"]!="PENDING":error("A proposta já foi concluída",409)
        if db.execute("SELECT 1 FROM approvals WHERE proposal_id=? AND founder_id=?",(proposal_id,u["id"])).fetchone():
            error("Já aprovaste esta decisão. É obrigatório outro fundador.",409)
        db.execute("INSERT INTO approvals(proposal_id,founder_id,approved_at) VALUES(?,?,?)",(proposal_id,u["id"],now()))
        count=db.execute("SELECT COUNT(*) c FROM approvals WHERE proposal_id=?",(proposal_id,)).fetchone()["c"]
        if count==2:
            execute_proposal(db,proposal,u["id"])
        audit(db,u["id"],"APPROVE_PROPOSAL","proposal",proposal_id,{"approvals":count})
    return {"ok":True,"approvals":count,"executed":count==2}

@router.get("/audit")
def audit_log(request:Request):
    auth(request,roles=ADMINS)
    return {"entries":rows("""SELECT a.id,a.action,a.entity_type,a.entity_id,a.detail,a.created_at,
                       u.username actor FROM audit_log a LEFT JOIN users u ON a.actor_id=u.id
                       ORDER BY a.created_at DESC LIMIT 200""")}
