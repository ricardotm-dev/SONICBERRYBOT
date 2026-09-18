import os
import re
import asyncio
import logging
import sqlite3
import httpx
import unicodedata
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    filters,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
)

load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

MI_USER_ID = 7654349208

SLSKD_URL = os.getenv("SLSKD_URL", "http://127.0.0.1:5030")
SLSKD_API_KEY = os.getenv("SLSKD_API_KEY", "supersecretkey123")
HEADERS = {"X-API-Key": SLSKD_API_KEY, "Content-Type": "application/json"}

STAGING_DIR = "/mnt/music/staging"
BEETS_DB_PATH = os.path.expanduser("~/.config/beets/musiclibrary.db")

AUDIO_EXTS = (".flac", ".mp3", ".m4a", ".wav", ".aac", ".ogg")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

SEARCH_QUERY, SELECT_TRACK = range(2)


class MusicFuzzyScorer:
    @staticmethod
    def _trimf(x: float, a: float, b: float, c: float) -> float:
        if x <= a or x >= c:
            return 0.0
        if a < x <= b:
            return (x - a) / (b - a)
        return (c - x) / (c - b)

    @staticmethod
    def _trapmf_left(x: float, a: float, b: float) -> float:
        if x <= a:
            return 1.0
        if a < x < b:
            return (b - x) / (b - a)
        return 0.0

    @staticmethod
    def _trapmf_right(x: float, a: float, b: float) -> float:
        if x >= b:
            return 1.0
        if a < x < b:
            return (x - a) / (b - a)
        return 0.0

    @classmethod
    def evaluate(cls, size_mb: float, queue_len: int, speed_kbps: float, has_slot: bool, is_flac: bool) -> float:
        mu_size_bad = cls._trapmf_left(size_mb, 1.0, 3.0)
        mu_size_sweet = cls._trimf(size_mb, 12.0, 35.0, 90.0) 
        mu_size_heavy = cls._trapmf_right(size_mb, 80.0, 150.0) 

        mu_q_free = 1.0 if (queue_len == 0 and has_slot) else 0.0
        mu_q_short = cls._trimf(queue_len, 0.0, 2.0, 6.0)
        mu_q_crowded = cls._trapmf_right(queue_len, 5.0, 15.0)

        mu_spd_slow = cls._trapmf_left(speed_kbps, 40.0, 180.0)
        mu_spd_fast = cls._trapmf_right(speed_kbps, 400.0, 1200.0)

        rules = [
            (min(mu_size_sweet, mu_q_free, mu_spd_fast), 100.0 if is_flac else 40.0),
            (min(mu_size_sweet, mu_q_short), 85.0 if is_flac else 30.0),
            (min(mu_size_heavy, mu_spd_fast, max(mu_q_free, mu_q_short)), 70.0 if is_flac else 20.0),
            (min(mu_size_heavy, mu_spd_slow), 20.0),
            (mu_q_crowded, 10.0),
            (mu_size_bad, 0.0),
        ]

        total_weight = sum(w for w, _ in rules)
        if total_weight == 0.0:
            return 35.0

        return round(sum(w * z for w, z in rules) / total_weight, 2)


def parse_music_query(text: str) -> str:
    query = text.strip()
    
    query = unicodedata.normalize('NFKD', query).encode('ASCII', 'ignore').decode('utf-8')

    by_match = re.match(r"^(.*?)\s+by\s+(.*)$", query, re.IGNORECASE)
    if by_match:
        query = f"{by_match.group(2)} {by_match.group(1)}"

    query = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", query)
    query = re.sub(
        r"\b(feat\.?|ft\.?|featuring|prod\.?|official|video|audio|remaster(ed)?)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"[,;:\-_/|]", " ", query)
    return " ".join(query.split())


def check_local_library(clean_query: str):
    if not os.path.exists(BEETS_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(BEETS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artist, album, title FROM items WHERE title LIKE ? OR artist LIKE ? LIMIT 1",
            (f"%{clean_query}%", f"%{clean_query}%"),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"artist": row[0], "album": row[1], "title": row[2]}
    except Exception as e:
        logging.error(f"Error checking local beets DB: {e}")
    return None


async def get_canonical_suggestion(raw_text: str):
    try:
        url = "https://itunes.apple.com/search"
        params = {"term": raw_text, "entity": "song", "limit": 1}
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    raw_artist = results[0].get("artistName", "")
                    primary_artist = re.split(r"[,&]|\s+(?:feat\.?|ft\.?|featuring|with|x)\s+", raw_artist, flags=re.IGNORECASE)[0].strip()
                    
                    track = results[0].get("trackName", "")
                    clean_track = re.sub(r"[\(\[\{].*?[\)\]\}]", "", track).strip()
                    
                    display_suggestion = f"{primary_artist} - {clean_track}"
                    clean_search = f"{primary_artist} {clean_track}"
                    return display_suggestion, clean_search
    except Exception as e:
        logging.error(f"Error fetching music suggestion: {e}")
    return None, None


async def run_beets_import() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "beet", "import", "-s", "-q", STAGING_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception as e:
        logging.error(f"Error running beets import: {e}")
        return False


async def monitor_download(bot, chat_id: int, username: str, filename: str, display_name: str):
    for _ in range(120):
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
                resp = await client.get(f"{SLSKD_URL}/api/v0/transfers/downloads")
                if resp.status_code != 200:
                    continue
                data = resp.json()

                file_state = None
                exception_msg = ""
                for peer in data:
                    if peer.get("username", "").lower() == username.lower():
                        for directory in peer.get("directories", []):
                            for f in directory.get("files", []):
                                if f.get("filename") == filename:
                                    file_state = f.get("state", "")
                                    exception_msg = f.get("exception", "")
                                    break

                if not file_state:
                    continue

                if "Completed, Succeeded" in file_state or file_state == "Succeeded":
                    clean_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=f"✨ **Download finished!**\n\nTagging `{display_name}` via Beets...",
                        parse_mode="Markdown",
                    )

                    success = await run_beets_import()
                    status_txt = "Tags & cover art verified" if success else "Imported as-is (bootleg/preserved)"

                    await clean_msg.edit_text(
                        f"🎉 **Ready in Navidrome!**\n\n"
                        f"🎵 `{display_name}`\n"
                        f"📁 Status: `{status_txt}`\n"
                        f"🏷️ Destination: `/mnt/music/library`",
                        parse_mode="Markdown",
                    )
                    return

                if any(err in file_state for err in ("Rejected", "Aborted", "Cancelled", "Errored")):
                    err_detail = f"\nMotivo: `{exception_msg}`" if exception_msg else ""
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"⚠️ **Descarga rechazada o abortada**\n\n"
                            f"🎵 `{display_name}`\n"
                            f"👤 Peer: `{username}`\n"
                            f"Estado: `{file_state}`{err_detail}\n\n"
                            "El peer rechazó la transferencia. Intenta con otro resultado usando /start."
                        ),
                        parse_mode="Markdown",
                    )
                    return
        except Exception as e:
            logging.error(f"Error in monitor_download: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Access granted! (ID: {user_id})\n\n"
        "What song are you looking for?\n"
        "Formats accepted: `Artist - Title`, `Title, Artist` or `Title by Artist`\n"
        "Send your query (or /cancel to abort):"
    )
    return SEARCH_QUERY


async def execute_slskd_search(clean_query: str, status_msg, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["search_query"] = clean_query

    async with httpx.AsyncClient(headers=HEADERS, timeout=35.0) as client:
        try:
            resp = await client.post(
                f"{SLSKD_URL}/api/v0/searches",
                json={"searchText": clean_query},
            )
            resp.raise_for_status()
            search_id = resp.json()["id"]
        except Exception as e:
            logging.error(f"Search init failed: {e}")
            await status_msg.edit_text("❌ Failed to contact Slskd.")
            return ConversationHandler.END

        candidates = []
        for second in range(1, 23):
            await asyncio.sleep(1)
            try:
                resp = await client.get(f"{SLSKD_URL}/api/v0/searches/{search_id}/responses")
                if resp.status_code == 200:
                    responses = resp.json()
                    candidates = []
                    for peer in responses:
                        username = peer.get("username")
                        speed = peer.get("uploadSpeed") or 0
                        speed_kbps = speed / 1024
                        has_slots = bool(peer.get("hasFreeUploadSlot", False))
                        queue_len = peer.get("queueLength")
                        if queue_len is None:
                            queue_len = 999

                        for f in peer.get("files", []):
                            fname = f.get("filename", "")
                            if fname.lower().endswith(AUDIO_EXTS):
                                raw_size = f.get("size") or 0
                                size_mb = raw_size / (1024 * 1024)
                                ext = os.path.splitext(fname)[1].lower()
                                is_flac = ext == ".flac"

                                if 1.0 <= size_mb <= 200.0:
                                    fuzzy_score = MusicFuzzyScorer.evaluate(
                                        size_mb=size_mb,
                                        queue_len=queue_len,
                                        speed_kbps=speed_kbps,
                                        has_slot=has_slots,
                                        is_flac=is_flac,
                                    )

                                    candidates.append({
                                        "username": username,
                                        "filename": fname,
                                        "size": raw_size,
                                        "size_mb": round(size_mb, 1),
                                        "speed": speed,
                                        "speed_kbps": round(speed_kbps),
                                        "has_slots": has_slots,
                                        "queue_len": queue_len,
                                        "ext": ext,
                                        "score": fuzzy_score,
                                    })

                    if len(candidates) >= 50 and second >= 10:
                        break
            except Exception as e:
                logging.error(f"Polling error: {e}")

    if not candidates:
        display_sug, clean_sug = await get_canonical_suggestion(clean_query)
        if display_sug and clean_sug and clean_sug.lower() != clean_query.lower():
            context.user_data["suggested_query"] = clean_sug
            
            title_only = clean_sug.split(" ", 1)[-1] if " " in clean_sug else clean_sug
            context.user_data["title_only_query"] = title_only

            keyboard = [
                [InlineKeyboardButton(f"🔍 {display_sug}", callback_data="sug_accept")],
                [InlineKeyboardButton(f"🎵 Buscar solo el título: '{title_only}'", callback_data="sug_title")],
                [InlineKeyboardButton("❌ Cancel", callback_data="dl_cancel")],
            ]
            await status_msg.edit_text(
                f"⚠️ No results found for `{clean_query}`.\n\n"
                f"Did you mean:\n👉 **{display_sug}**?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return SELECT_TRACK

        await status_msg.edit_text(f"⚠️ No audio files found for '{clean_query}'. Try /start with another query.")
        return ConversationHandler.END

    candidates.sort(key=lambda x: x["score"], reverse=True)

    unique_candidates = []
    seen = set()
    for c in candidates:
        key = (c["username"], c["filename"])
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)
        if len(unique_candidates) == 5:
            break

    context.user_data["results"] = unique_candidates

    keyboard = []
    for idx, item in enumerate(unique_candidates):
        filename_only = item["filename"].replace("/", "\\").split("\\")[-1]
        name, _ = os.path.splitext(filename_only)
        clean_name = name[:20] if len(name) > 20 else name
        format_tag = item["ext"].replace(".", "").upper()

        label = f"[{format_tag}] {clean_name}.. ({item['size_mb']}MB | {item['speed_kbps']}kB/s)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dl_{idx}")])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="dl_cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await status_msg.edit_text(f"Tracks for '{clean_query}' (Fuzzy Engine ranked):", reply_markup=reply_markup)
    return SELECT_TRACK


async def capture_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_query = update.message.text
    clean_query = parse_music_query(raw_query)

    local_match = check_local_library(clean_query)
    header_text = ""
    if local_match:
        header_text = (
            f"ℹ️ *Nota: Ya tienes '{local_match['title']}' de {local_match['artist']} "
            f"en '{local_match['album']}'.*\n\n"
        )

    status_msg = await update.message.reply_text(
        f"{header_text}🔍 Searching for '{clean_query}' on Soulseek...",
        parse_mode="Markdown" if local_match else None,
    )
    return await execute_slskd_search(clean_query, status_msg, context)


async def handle_callback_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "dl_cancel":
        await query.edit_message_text("Operation cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    if data == "sug_title":
        title_q = context.user_data.get("title_only_query")
        if not title_q:
            await query.edit_message_text("Suggestion expired. Try /start again.")
            return ConversationHandler.END
        
        await query.edit_message_text(f"🔍 Searching for '{title_q}'...")
        return await execute_slskd_search(title_q, query.message, context)

    if data == "sug_accept":
        suggested = context.user_data.get("suggested_query")
        if not suggested:
            await query.edit_message_text("Suggestion expired. Try /start again.")
            return ConversationHandler.END

        await query.edit_message_text(f"🔍 Searching for '{suggested}'...")
        return await execute_slskd_search(suggested, query.message, context)

    idx = int(data.split("_")[1])
    selected = context.user_data["results"][idx]

    username = selected["username"]
    filename = selected["filename"]
    size = selected["size"]
    clean_display_name = filename.replace("/", "\\").split("\\")[-1]

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{SLSKD_URL}/api/v0/transfers/downloads/{username}",
                json=[{"filename": filename, "size": size}],
            )
            resp.raise_for_status()

            await query.edit_message_text(
                f"⏳ **Download queued**\n\n"
                f"🎵 `{clean_display_name}`\n"
                f"👤 Peer: `{username}`\n"
                f"📦 Size: `{selected['size_mb']} MB`\n"
                f"🧠 Fuzzy Score: `{selected['score']}/100`\n\n"
                f"Monitoring transfer... I'll tag it and notify you once it's in `/mnt/music/library`.",
                parse_mode="Markdown",
            )

            asyncio.create_task(
                monitor_download(
                    context.bot,
                    update.effective_chat.id,
                    username,
                    filename,
                    clean_display_name,
                )
            )
        except Exception as e:
            logging.error(f"Download queue failed: {e}")
            await query.edit_message_text("❌ An error occurred while queuing the download.")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Operation aborted.")
    return ConversationHandler.END


if __name__ == "__main__":
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN missing in ~/.env")

    application = ApplicationBuilder().token(TOKEN).build()
    user_filter = filters.User(user_id=MI_USER_ID)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start, filters=user_filter)],
        states={
            SEARCH_QUERY: [
                MessageHandler(filters.TEXT & (~filters.COMMAND) & user_filter, capture_query)
            ],
            SELECT_TRACK: [
                CallbackQueryHandler(handle_callback_selection, pattern=r"^(dl_|sug_)")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel, filters=user_filter)],
        per_message=False,
    )

    application.add_handler(conv_handler)
    application.run_polling()