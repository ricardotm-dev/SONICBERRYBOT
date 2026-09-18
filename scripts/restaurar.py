import os
import re
import shutil
import sys
from mutagen import File

DEST_DIR = "/mnt/music/library"
SEARCH_DIRS = ["/mnt/music/staging", "/mnt/music"]
EXTS = (".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav")

def sanitize(name: str) -> str:
    if not name:
        return "Desconocido"
    clean = name.replace("/", "-").replace("\\", "-")
    clean = re.sub(r'[:*?"<>|]', '', clean).strip()
    return clean if clean else "Desconocido"

def get_tags(filepath):
    try:
        audio = File(filepath, easy=True)
        if audio is None:
            return "Desconocido", "Desconocido"
        artist = audio.get("albumartist", audio.get("artist", ["Desconocido"]))[0]
        album = audio.get("album", ["Desconocido"])[0]
        return sanitize(artist), sanitize(album)
    except Exception:
        return "Desconocido", "Desconocido"

def run(dry_run=True):
    print(f"\n--- MODO: {'SIMULACIÓN (Sin mover nada)' if dry_run else 'REAL (Moviendo archivos)'} ---\n")
    files_to_move = []

    for base_dir in SEARCH_DIRS:
        if not os.path.exists(base_dir):
            continue
        if base_dir == "/mnt/music":
            for item in os.listdir(base_dir):
                p = os.path.join(base_dir, item)
                if os.path.isfile(p) and p.lower().endswith(EXTS):
                    files_to_move.append(p)
        else:
            for root, _, filenames in os.walk(base_dir):
                for f in filenames:
                    if f.lower().endswith(EXTS):
                        files_to_move.append(os.path.join(root, f))

    if not files_to_move:
        print("No se encontraron archivos sueltos para organizar.")
        return

    moved, unknown = 0, 0
    for filepath in files_to_move:
        fname = os.path.basename(filepath)
        artist, album = get_tags(filepath)

        if artist == "Desconocido" or album == "Desconocido":
            target_folder = os.path.join(DEST_DIR, "_Revisar_Sin_Tags")
            unknown += 1
        else:
            target_folder = os.path.join(DEST_DIR, artist, album)

        target_file = os.path.join(target_folder, fname)

        if dry_run:
            print(f"[SIMULADO] {fname}\n       ↳ {target_folder}/")
        else:
            os.makedirs(target_folder, exist_ok=True)
            if not os.path.exists(target_file):
                shutil.move(filepath, target_file)
                moved += 1

    print(f"\nTotal detectados: {len(files_to_move)}")
    if not dry_run:
        print(f"Archivos movidos exitosamente: {moved}")
    if unknown > 0:
        print(f"Archivos sin tags claros: {unknown}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--exec":
        run(dry_run=False)
    else:
        run(dry_run=True)
        print("\nPara ejecutar el movimiento real corre:")
        print("python3 ~/restaurar.py --exec\n")
