"""One-time, local, interactive setup. NEVER exposed as an HTTP endpoint."""
import getpass
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import initialize, transaction
from app.security import hash_password, uid, now


def bootstrap(founders):
    if len(founders) != 2 or len({f[0].strip().lower() for f in founders}) != 2:
        raise ValueError("São necessários dois emails distintos.")
    if any(len(f[2]) < 12 for f in founders):
        raise ValueError("Palavra-passe de fundador: mínimo 12 caracteres.")
    initialize()
    with transaction(immediate=True) as db:
        existing = db.execute("SELECT COUNT(*) AS c FROM users WHERE role='FUNDADOR'").fetchone()["c"]
        if existing:
            raise ValueError("Configuração já efetuada. Não é permitido repetir.")
        for email, name, password in founders:
            db.execute("INSERT INTO users(id,email,password_hash,username,role,status,created_at,approved_at) VALUES(?,?,?,?,'FUNDADOR','ACTIVE',?,?)",
                       (uid(), email.strip().lower(), hash_password(password), name.strip(), now(), now()))
    print("Dois fundadores registados com igual autoridade.")

if __name__ == "__main__":
    print("Configuração inicial: dois fundadores (não usar contas pessoais de demonstração).")
    entries=[]
    for i in (1,2):
        email=input(f"Email do fundador {i}: ").strip()
        name=input(f"Nome do fundador {i}: ").strip()
        password=getpass.getpass(f"Palavra-passe do fundador {i} (mín. 12): ")
        entries.append((email,name,password))
    try:
        bootstrap(entries)
    except (sqlite3.IntegrityError,ValueError) as exc:
        print("Erro:",exc)
        sys.exit(1)
