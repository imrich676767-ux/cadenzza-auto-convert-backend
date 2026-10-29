
import io
import zipfile
from collections import Counter
from pathlib import PurePosixPath

from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(title="CADENZZA Auto Inspect API")

MAX_UPLOAD = 20 * 1024 * 1024
MAX_FILES = 5000
MAX_UNPACKED = 100 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".tga",
    ".fbx", ".obj", ".mtl", ".json", ".txt",
    ".unity3d", ".asset", ".mat", ".prefab",
    ".bnk", ".wav", ".ogg", ".mp3", ".zip"
}


@app.get("/")
def home():
    return {
        "service": "CADENZZA Auto Inspect",
        "status": "online",
        "mode": "inspect_only",
        "note": "This API inspects ZIP files; it does not build Unity AssetBundles."
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/inspect")
async def inspect_zip(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .zip file.")

    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "ZIP exceeds the 20 MB upload limit.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid or damaged ZIP file.")

    try:
        entries = archive.infolist()

        if len(entries) > MAX_FILES:
            raise HTTPException(413, "ZIP contains too many entries.")

        total_size = 0
        extensions = Counter()
        samples = []
        warnings = []

        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)

            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise HTTPException(400, "ZIP contains an unsafe path.")

            if entry.flag_bits & 1:
                raise HTTPException(400, "Encrypted ZIP entries are not supported.")

            if entry.file_size < 0:
                raise HTTPException(400, "Invalid entry size.")

            total_size += entry.file_size
            if total_size > MAX_UNPACKED:
                raise HTTPException(413, "Unpacked ZIP contents exceed 100 MB.")

            if entry.file_size > 0 and entry.compress_size == 0:
                raise HTTPException(400, "Invalid compressed entry.")

            if entry.compress_size > 0:
                ratio = entry.file_size / entry.compress_size
                if ratio > 200:
                    raise HTTPException(400, "ZIP compression ratio is too high.")

            if entry.is_dir():
                continue

            ext = path.suffix.lower() or "[no extension]"
            extensions[ext] += 1

            if len(samples) < 100:
                samples.append({
                    "path": name,
                    "size_bytes": entry.file_size,
                    "extension": ext
                })

        if ".unity3d" in extensions:
            warnings.append(
                "Unity bundle files found. Their contents are not converted by this API."
            )

        if not any(ext in ALLOWED_EXTENSIONS for ext in extensions):
            warnings.append("No commonly recognized asset file types were found.")

        return {
            "filename": file.filename,
            "zip_size_bytes": len(data),
            "file_count": sum(extensions.values()),
            "unpacked_size_bytes": total_size,
            "extensions": dict(extensions),
            "sample_files": samples,
            "warnings": warnings,
            "conversion_status": "not_built",
            "message": "Inspection complete. No iOS AssetBundle has been created."
        }
    finally:
        archive.close()
