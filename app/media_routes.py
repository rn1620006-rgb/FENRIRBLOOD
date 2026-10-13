import io
from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Response
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from . import config
from .core import auth,error,audit
from .db import transaction,one
from .security import now,uid

router=APIRouter(prefix="/api/media",tags=["media"])
MAX_BYTES=5*1024*1024
MAX_PIXELS=16_000_000

@router.post("")
async def upload(request:Request,file:UploadFile=File(...)):
    actor=auth(request)
    if file.content_type not in {"image/jpeg","image/png","image/webp"}:
        error("Formato não permitido: usa JPEG, PNG ou WebP")
    body=await file.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES:error("Imagem maior que 5 MB")
    try:
        with Image.open(io.BytesIO(body)) as img:
            if img.format not in ("JPEG","PNG","WEBP"):
                error("O ficheiro não corresponde ao formato declarado")
            if img.width*img.height>MAX_PIXELS:
                error("A imagem ultrapassa o limite de resolução")
            img=ImageOps.exif_transpose(img)
            img.thumbnail((1800,1800),Image.Resampling.LANCZOS)
            if img.mode not in ("RGB","RGBA"):
                img=img.convert("RGBA" if "A" in img.getbands() else "RGB")
            width,height=img.size
            buffer=io.BytesIO()
            img.save(buffer,format="WEBP",quality=83,method=5)
            result=buffer.getvalue()
    except (OSError,UnidentifiedImageError,ValueError):
        error("A imagem enviada não é válida")
    media_id=uid()
    media_dir=config.DB_PATH.parent / "uploads"
    media_dir.mkdir(parents=True,exist_ok=True)
    safe_name=media_id+".webp"
    path=media_dir / safe_name
    with transaction(immediate=True) as db:
        from datetime import datetime,timedelta,timezone
        cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(timespec="seconds")
        daily=db.execute("SELECT COUNT(*) AS c FROM media WHERE uploader_id=? AND created_at>?",(actor["id"],cutoff)).fetchone()["c"]
        if daily>=20:error("Limite de 20 imagens por dia atingido",429)
        try:
            path.write_bytes(result)
            db.execute("INSERT INTO media(id,uploader_id,file_name,bytes,width,height,created_at) VALUES(?,?,?,?,?,?,?)",
                       (media_id,actor["id"],safe_name,len(result),width,height,now()))
            audit(db,actor["id"],"UPLOAD_MEDIA","media",media_id,{"bytes":len(result)})
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return {"id":media_id,"url":"/api/media/"+media_id,"width":width,"height":height}

@router.get("/{media_id}")
def access_media(media_id:str,request:Request):
    auth(request)
    media=one("SELECT * FROM media WHERE id=?",(media_id,))
    if not media:error("Imagem não encontrada",404)
    # No arbitrary filename is accepted. Files are available only to approved members.
    file_path=config.DB_PATH.parent / "uploads" / media["file_name"]
    if not file_path.is_file():error("Imagem temporariamente indisponível",404)
    return FileResponse(file_path,media_type="image/webp",headers={"Cache-Control":"private, max-age=60"})
