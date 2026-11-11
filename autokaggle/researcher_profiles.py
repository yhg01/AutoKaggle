"""Researcher display names. Account IDs and access rights stay separate."""
import unicodedata

from fastapi import HTTPException

from .store import now


def validate_name(value):
    if not isinstance(value, str) or any(unicodedata.category(ch).startswith("C") for ch in value):
        raise HTTPException(400, "Enter a name with 1 to 100 visible characters.")
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if not 1 <= len(value) <= 100:
        raise HTTPException(400, "Enter a name with 1 to 100 visible characters.")
    return value


def set_name(store, account, name, actor):
    name = validate_name(name)
    with store.connection() as con:
        if not con.execute("SELECT 1 FROM email_accounts WHERE id=?", (account,)).fetchone():
            raise HTTPException(404, "The verified researcher account is unavailable.")
        con.execute("INSERT INTO researcher_profiles (account,name,updated_at,updated_by) VALUES (?,?,?,?) "
                    "ON CONFLICT(account) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                    (account, name, now(), actor))
    return name


def project_researcher(store, project_id):
    with store.connection() as con:
        row = con.execute("SELECT COALESCE(r.name,''), a.id IS NOT NULL FROM projects p "
                          "LEFT JOIN researcher_profiles r ON r.account=p.owner "
                          "LEFT JOIN email_accounts a ON a.id=p.owner WHERE p.id=?", (project_id,)).fetchone()
    return {"name": row[0], "can_edit": bool(row[1])} if row else None
