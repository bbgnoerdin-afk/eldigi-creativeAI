import os

import time

import uuid

import io

import json

import asyncio

from datetime import datetime, timezone

import pytz

from PIL import Image, ImageFile

import aiofiles



# ==========================================

# AUTO INSTALL DEPENDENCIES

# ==========================================

from motor.motor_asyncio import AsyncIOMotorClient

import dns.resolver

from dotenv import load_dotenv

# IMPORT AFFILIATE UTILS

from utils.affiliate import (

    init_affiliate_db, get_or_create_affiliate, register_referral, process_commission,

    handle_affiliate_menu, handle_riwayat_wd,

    handle_tarik_komisi, handle_tarik_locked, handle_wd_amount, handle_wd_info

)





# UTILS IMPORTS

from utils.pakasir import create_payment, cancel_payment, check_payment_status

from utils.geminigen import get_video_token_sync, get_geminigen_task_sync, poll_geminigen_task, get_geminigen_image_sync

from utils.motion import submit_motion_task, poll_motion_task



# IMPORT AFFILIATE UTILS

from utils.affiliate import (

    init_affiliate_db, get_or_create_affiliate, register_referral, process_commission,

    handle_affiliate_menu, handle_riwayat_wd

)



load_dotenv()



Image.MAX_IMAGE_PIXELS = None  

ImageFile.LOAD_TRUNCATED_IMAGES = True



from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, ReplyKeyboardMarkup

from telegram.ext import (

    Application, CommandHandler, MessageHandler, CallbackQueryHandler,

    filters, ConversationHandler, ContextTypes,

)

# ==========================================
# BOT, ADMIN & PAKASIR CONFIGURATION
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID")) 
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
API_KEY = os.getenv("PAKASIR_API_KEY")
PROJECT = os.getenv("PAKASIR_PROJECT")

# KONFIGURASI BOT & SOSIAL MEDIA DARI .ENV
BOT_NAME = os.environ["BOT_NAME"]
URL_ADMIN = os.environ["URL_ADMIN"]
URL_CHANNEL = os.environ["URL_CHANNEL"]
URL_WA = os.environ["URL_WA"]
URL_TIKTOK = os.environ["URL_TIKTOK"]

# GANTI TARGET CHANNEL LOG DI BAWAH INI SESUAI PERMINTAAN
LOG_CHANNEL = os.getenv("LOG_CHANNEL")
LOG_BELIPOIN = os.getenv("LOG_BELIPOIN")
LOG_PEMBAYARANKOMISI = os.getenv("LOG_PEMBAYARANKOMISI")

JKT = pytz.timezone('Asia/Jakarta')

if not BOT_TOKEN or not MONGO_URI:
    print("[-] ERROR: BOT_TOKEN atau MONGO_URI tidak ditemukan di .env!")
    sys.exit(1)

# BIAYA GENERATE SETIAP FITUR
COSTS = {
    "image_gen": 15, "t2v": 15, "i2v": 30, "motion": 40
}

# ==========================================
# MONGODB CONNECTION (ASYNC MENGGUNAKAN MOTOR)
# ==========================================
import certifi 

users_col = None 
orders_col = None
tasks_col = None
affiliates_col = None   
withdrawals_col = None  
pricing_col = None

# SEMAPHORE UNTUK MEMBATASI MAKSIMAL 20 TASK GENERATE BERJALAN BERSAMAAN
GLOBAL_TASK_SEMAPHORE = asyncio.Semaphore(20)

try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8', '8.8.4.4', '1.1.1.1']
    
    mongo_client = AsyncIOMotorClient(
        MONGO_URI, 
        serverSelectionTimeoutMS=5000,
        tlsCAFile=certifi.where(),
        maxPoolSize=100
    )
    db = mongo_client["singebutai_db"] 
    users_col = db["users"]        
    orders_col = db["orders"]
    tasks_col = db["tasks"]
    affiliates_col = db["affiliates"]   
    withdrawals_col = db["withdrawals"] 
    pricing_col = db["pricing"] 
    
    asyncio.get_event_loop().run_until_complete(tasks_col.create_index("createdAt", expireAfterSeconds=900))
    
    try:
        init_affiliate_db(db)
    except Exception as e:
        print(f"[-] Init Affiliate DB Note: {e}")
    
    print("[+] Async MongoDB Connected Successfully with Certifi SSL!")
except Exception as e:
    print(f"[-] MongoDB Connection Failed: {e}")

CHOOSING_FEATURE = 0
CHOOSING_QUANTITY = 1
CHOOSING_RATIO = 2
CHOOSING_MODEL = 3
WAITING_IMAGE = 4
WAITING_PROMPT = 5
CHOOSING_VIDEO_RATIO = 6
CHOOSING_VEO_MODE = 7
WAITING_GROK_IMAGES = 8
WAITING_MOTION_IMAGE = 9
WAITING_MOTION_URL = 10
CHOOSING_MOTION_MODE = 11
WAITING_WD_AMOUNT = 12
WAITING_WD_INFO = 13
WAITING_INTERESTED = 14

ongoing_tasks = {}
PACKAGES = {}

# ==========================================
# DYNAMIC PACKAGES LOADER (ASYNC)
# ==========================================
async def load_packages():
    packages = {}
    try:
        if pricing_col is not None:
            standards = await pricing_col.find({"type": "standard"}).to_list(length=None)
            for pkg in standards:
                points = pkg["points"]
                price = pkg["price"]
                pkg_key = f"pkg_{points}"
                packages[pkg_key] = {
                    "points": points, 
                    "price": price, 
                    "name": f"{points:,} Koin".replace(',', '.')
                }
            
            unlim = await pricing_col.find_one({"type": "unlimited"})
            if unlim:
                packages["pkg_unlim"] = {
                    "points": "unlimited", 
                    "price": unlim["price"], 
                    "name": "UNLIMITED"
                }
            else:
                packages["pkg_unlim"] = {
                    "points": "unlimited", 
                    "price": 149000, 
                    "name": "UNLIMITED"
                }
    except Exception as e:
        print(f"[-] Gagal membaca harga dari MongoDB: {e}")
        
    return packages

# ==========================================
# HELPERS
# ==========================================
def cleanup_temp_files(user_data):
    """Membersihkan file gambar sementara dari disk jika proses dibatalkan/gagal"""
    if 'img_path' in user_data and os.path.exists(user_data['img_path']):
        try: os.remove(user_data['img_path'])
        except: pass
    if 'images' in user_data:
        for img_dict in user_data['images']:
            if 'path' in img_dict and os.path.exists(img_dict['path']):
                try: os.remove(img_dict['path'])
                except: pass

def get_now_jkt():
    now = datetime.now(JKT)
    hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    bulan = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
    return f"{hari[now.weekday()]}, {now.day:02d} {bulan[now.month - 1]} {now.year} ~ {now.strftime('%H:%M:%S')} WIB"

def get_simple_time():
    return datetime.now(JKT).strftime('%Y-%m-%d %H:%M:%S')

def rupiah(n):
    return "Rp {:,}".format(int(n)).replace(",", ".")

def generate_qr(data):
    import qrcode
    buffer = io.BytesIO()
    qrcode.make(data).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def get_or_create_user(chat_id, username):
    user = await users_col.find_one({"user_id": chat_id})
    is_new = False
    if not user:
        is_new = True
        user = {
            "user_id": chat_id,
            "username": username,
            "points": 80, 
            "total_generates": 0,
            "joined_at": get_simple_time()
        }
        await users_col.insert_one(user)
    return user, is_new

async def add_points(chat_id, points_to_add):
    user = await users_col.find_one({"user_id": chat_id})
    if user:
        if user["points"] == "unlimited" and points_to_add != "unlimited": return
        if points_to_add == "unlimited": new_pts = "unlimited"
        else: new_pts = (user["points"] if isinstance(user["points"], int) else 0) + points_to_add
        await users_col.update_one({"user_id": chat_id}, {"$set": {"points": new_pts}})

async def send_new_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode="Markdown"):
    chat_id = update.effective_chat.id
    
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass
            
    if update.callback_query:
        try: await update.callback_query.answer()
        except Exception: pass

    new_msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)
    context.user_data['last_bot_msg_id'] = new_msg.message_id
    return new_msg

# ==========================================
# MENUS & KEYBOARDS (INLINE)
# ==========================================
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎨 IMAGE GENERATION", callback_data="menu_image"), InlineKeyboardButton("🎥 VIDEO GENERATION", callback_data="menu_video")],
        [InlineKeyboardButton("🕺 MOTION CONTROL", callback_data="feat_motion")],
        [InlineKeyboardButton("💳 Beli Poin", callback_data="menu_buy"), InlineKeyboardButton("📋 TASK LIST", callback_data="menu_task")], 
        [InlineKeyboardButton("🤝 Affiliate Program", callback_data="menu_affiliate"), InlineKeyboardButton("🏆 Top Leaderboard", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📚 TUTORIAL PENGGUNAAN", callback_data="menu_tutorial"), InlineKeyboardButton("👨‍💻 INFO DEVELOPER", callback_data="menu_developer")],
        [InlineKeyboardButton("ℹ️ INFORMASI VERSI", callback_data="menu_version")],
        [InlineKeyboardButton("❌ Tutup", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_video_gen_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎬 Text to Video", callback_data="feat_t2v"), InlineKeyboardButton("🎞️ Image to Video", callback_data="feat_i2v")],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# PAKASIR PAYMENT LOGIC
# ==========================================
async def cek_pembayaran_loop(context_or_app, order_data: dict):
    bot = context_or_app.bot 
    order_id = order_data["order_id"]
    amount = order_data["amount"]
    chat_id = order_data["chat_id"]
    pkg_key = order_data["pkg_key"]
    start_time = order_data["created_at"]
    msg_id = order_data.get("msg_id")

    current_packages = await load_packages()

    while True:
        curr_order = await orders_col.find_one({"order_id": order_id})
        if not curr_order or curr_order["status"] != "pending": return

        if time.time() - start_time > 300:
            await asyncio.to_thread(cancel_payment, amount, order_id, PROJECT, API_KEY)
            await orders_col.delete_one({"order_id": order_id})
            if msg_id:
                try: await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except: pass
            try: await bot.send_message(chat_id, f"❌ **Waktu Habis!**\nPembayaran untuk `Order {order_id}` dibatalkan karena melewati batas 5 menit.", parse_mode="Markdown")
            except: pass
            return

        is_completed = await asyncio.to_thread(check_payment_status, amount, order_id, PROJECT, API_KEY)
        if is_completed:
            await orders_col.delete_one({"order_id": order_id})
            
            pkg_info = current_packages.get(pkg_key, {"points": 0, "name": "Unknown Package"})
            added_pts = pkg_info["points"]
            
            user_data = await users_col.find_one({"user_id": chat_id})
            buyer_username = user_data.get("username", "TanpaUsername") if user_data else "TanpaUsername"
            
            await process_commission(chat_id, buyer_username, amount, added_pts, bot, LOG_BELIPOIN)
            await add_points(chat_id, added_pts)
            
            if msg_id:
                try: await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except: pass
            
            success_msg = f"🎉 **PEMBAYARAN BERHASIL!** 🎉\n\n🧾 **Order ID** : `{order_id}`\n🛍️ **Paket** : {pkg_info['name']}\n\n_Poin Anda telah ditambahkan. Selamat menikmati layanan kami!_"
            try: await bot.send_message(chat_id, success_msg, parse_mode="Markdown")
            except: pass
            
            log_text = f"💰 <b>TOPUP BERHASIL</b>\n\n🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n📦 <b>Paket:</b> {pkg_info['name']}\n💵 <b>Nominal:</b> {rupiah(amount)}\n🧾 <b>Order ID:</b> {order_id}\n⏰ <b>Waktu:</b> {get_simple_time()}"
            try: await bot.send_message(chat_id=LOG_BELIPOIN, text=log_text, parse_mode="HTML")
            except: pass
            return
        
        await asyncio.sleep(5)

# ==========================================
# RESUME LOGIC (RUNS ON STARTUP)
# ==========================================
async def resume_pending_orders(app: Application):
    if orders_col is None: return 
    pending_orders = await orders_col.find({"status": "pending"}).to_list(length=None)
    for order in pending_orders:
        if time.time() - order["created_at"] > 300:
            await orders_col.delete_one({"order_id": order["order_id"]})
            await asyncio.to_thread(cancel_payment, order["amount"], order["order_id"], PROJECT, API_KEY)
        else:
            asyncio.create_task(cek_pembayaran_loop(app, order))

async def resume_polling_task(app: Application, db_task: dict):
    task_id = db_task['task_id']
    chat_id = db_task['chat_id']
    token = db_task.get('access_token')
    queue_id = db_task.get('queue_id')
    f_type = db_task.get('feature_type')
    model_choice = db_task.get('model_choice')
    status_msg_id = db_task.get('status_msg_id')
    start_time = db_task.get('start_time', time.time())
    username = db_task.get('username', 'Unknown')
    
    bot = app.bot
    is_gemini = f_type in ['i2v', 't2v'] and model_choice in ['veo_fast', 'veo_lite', 'grok']
    is_image_gen = f_type == 'image_gen'
    is_motion = f_type == 'motion'

    task_data = {
        "task_id": task_id,
        "feature_type": f_type,
        "model_choice": model_choice,
        "username": username,
        "chat_id": chat_id
    }
    cost = COSTS.get(f_type, 15)

    try:
        try: await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=f"⏳ *[Task {task_id}]*\n_Sistem Restart. Menyambung ulang proses generate..._", parse_mode="Markdown")
        except: pass

        if is_motion:
            uid = db_task.get('uid')
            status, result_url = await poll_motion_task(uid, queue_id, start_time)
        elif is_gemini or is_image_gen:
            status, result_url = await poll_geminigen_task(queue_id, token, is_image=is_image_gen)
        else: 
            raise Exception("Task tidak dikenali atau model lama tidak lagi didukung.")

        if status == "success":
            m, s = divmod(int(time.time() - start_time), 60)
            task_data['processing_time'] = f"{m} min {s} sec" if m > 0 else f"{s} sec"
            
            await send_task_log(bot, task_data, result_url) 
            await users_col.update_one({"user_id": chat_id}, {"$inc": {"total_generates": 1}})
            
            task_title = {"image_gen": "Image Generation", "t2v": "Text To Video", "i2v": "Image To Video", "motion": "Motion Control"}.get(f_type, "Task")
            msg = f"✅ <b>{task_title} Successfully Generated!</b>\n\n🤖 <b>Model:</b> {str(model_choice).upper()}\n⏱ <b>Processing Time:</b> {task_data['processing_time']}\n\n🔗 <b>Result Link:</b>\n<tg-spoiler>{result_url}</tg-spoiler>"
            
            try: await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
            except: pass
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                
        elif status == "failed": raise Exception(result_url or "Server blocked the prompt.")
        else: raise Exception("Process Timeout.")

    except Exception as e:
        safe_error = str(e).replace("<", "&lt;").replace(">", "&gt;") 
        if chat_id != ADMIN_ID:
            await add_points(chat_id, cost)
            fail_msg = f"❌ <b>[Task {task_id}] Failed:</b> {safe_error}\n\n<i>Poin {cost} Koin Anda telah dikembalikan.</i>"
        else:
            fail_msg = f"❌ <b>[Task {task_id}] Failed:</b> {safe_error}"
        try: await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=fail_msg, parse_mode="HTML")
        except: pass
    finally:
        if chat_id in ongoing_tasks and task_id in ongoing_tasks[chat_id]:
            del ongoing_tasks[chat_id][task_id]
        if tasks_col is not None:
            try: await tasks_col.delete_one({"task_id": task_id})
            except: pass

async def resume_pending_tasks(app: Application):
    if tasks_col is None: return 
    pending_tasks = await tasks_col.find({}).to_list(length=None)
    for task in pending_tasks:
        chat_id = task.get('chat_id')
        task_id = task.get('task_id')
        f_type = task.get('feature_type')
        prompt = task.get('prompt', 'Resumed Task')
        
        if chat_id and task_id:
            if chat_id not in ongoing_tasks: ongoing_tasks[chat_id] = {}
            ongoing_tasks[chat_id][task_id] = {"type": f_type, "prompt": prompt}
            
        if "queue_id" in task:
            asyncio.create_task(resume_polling_task(app, task))
        else:
            status_msg_id = task.get('status_msg_id')
            cost = COSTS.get(f_type, 15)
            if chat_id and task_id:
                if chat_id != ADMIN_ID:
                    await add_points(chat_id, cost)
                    msg = f"❌ <b>[Task {task_id}] Dibatalkan:</b> Bot mengalami restart sistem saat memproses task ini.\n\n<i>Poin {cost} Koin telah dikembalikan ke saldo Anda secara otomatis.</i>"
                else:
                    msg = f"❌ <b>[Task {task_id}] Dibatalkan:</b> Bot mengalami restart sistem."
                try: await app.bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=msg, parse_mode="HTML")
                except: pass
                
                if chat_id in ongoing_tasks and task_id in ongoing_tasks[chat_id]:
                    del ongoing_tasks[chat_id][task_id]
                await tasks_col.delete_one({"task_id": task_id})

async def post_init_setup(app: Application):
    global PACKAGES
    PACKAGES = await load_packages()
    asyncio.create_task(resume_pending_orders(app)) 
    asyncio.create_task(resume_pending_tasks(app)) 

# ==========================================
# ==========================================
# ADMIN COMMANDS (FULL IMPLEMENTATION)
# ==========================================
async def admin_cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    text = "🛠️ *DAFTAR COMMAND ADMIN* 🛠️\n\n• `/add_member <chat_id> <jumlah/unlimited>`\n• `/add_bonus <chat_id> <jumlah>`\n• `/delete_member <chat_id>`\n• `/list_member`\n• `/broadcast <teks>` / balas pesan\n• `/cmd`"
    await update.message.reply_text(text, parse_mode="Markdown")

# ==========================================
# TAMBAHAN FUNGSI ADMIN: WD & PRICELIST
# ==========================================
async def admin_success_wd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/success <kode_wd>`", parse_mode="Markdown")
        return
        
    wd_id = context.args[0]
    wd_data = await withdrawals_col.find_one({"wd_id": wd_id})
    
    if not wd_data:
        await update.message.reply_text(f"⚠️ Kode WD `{wd_id}` tidak ditemukan.", parse_mode="Markdown")
        return
    if wd_data['status'] == 'success':
        await update.message.reply_text("⚠️ Penarikan ini sudah pernah dikonfirmasi selesai.", parse_mode="Markdown")
        return
        
    # Update status di database menjadi success
    await withdrawals_col.update_one({"wd_id": wd_id}, {"$set": {"status": "success"}})
    await update.message.reply_text(f"✅ Penarikan `{wd_id}` berhasil dikonfirmasi selesai.", parse_mode="Markdown")
    
    # Kirim notifikasi ke user yang menarik komisi
    try:
        await context.bot.send_message(
            chat_id=wd_data['user_id'],
            text=f"🎉 **PENARIKAN BERHASIL!**\n\nPenarikan komisi Anda dengan kode `{wd_id}` sebesar **{rupiah(wd_data['amount'])}** telah berhasil ditransfer oleh Admin. Terima kasih!",
            parse_mode="Markdown"
        )
    except Exception:
        pass

async def admin_check_komisi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    
    # Mencari member yang memiliki saldo komisi > 0, diurutkan dari yang terbanyak
    users_with_komisi = await affiliates_col.find({"balance": {"$gt": 0}}).sort("balance", -1).to_list(length=None)
    
    if not users_with_komisi:
        await update.message.reply_text("✅ Saat ini tidak ada member yang memiliki saldo komisi aktif.")
        return
        
    # MENGGUNAKAN TAG HTML (<b> untuk bold, <code> untuk monospace)
    text = f"📋 <b>DAFTAR MEMBER DENGAN SALDO KOMISI ({len(users_with_komisi)})</b>\n\n"
    
    for aff in users_with_komisi:
        uid = aff.get('user_id', 'Unknown')
        uname = aff.get('username', 'TanpaUsername')
        balance = aff.get('balance', 0)
        total_comm = aff.get('total_commission', 0)
        
        line = f"👤 @{uname} (<code>{uid}</code>)\n💳 Saldo Aktif: <code>{rupiah(balance)}</code>\n💰 Total Riwayat: <code>{rupiah(total_comm)}</code>\n\n"
        
        # Mencegah error jika teks melebihi batas limit 4096 karakter dari Telegram
        if len(text) + len(line) > 4000:
            # UBAH PARSE MODE KE HTML
            await update.message.reply_text(text, parse_mode="HTML")
            text = "" # Reset variabel text untuk pesan selanjutnya
            
        text += line
        
    # Kirim sisa teks yang belum terkirim
    if text:
        # UBAH PARSE MODE KE HTML
        await update.message.reply_text(text, parse_mode="HTML")

async def admin_pricelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        # Format: /pricelist harga|poin (contoh: /pricelist 15000|100)
        args_str = " ".join(context.args)
        harga_str, poin_str = args_str.split("|")
        harga = int(harga_str.strip())
        poin = int(poin_str.strip())
        
        await pricing_col.update_one(
            {"points": poin, "type": "standard"},
            {"$set": {"price": harga, "points": poin, "type": "standard"}},
            upsert=True
        )
        
        # Refresh packages di memory
        global PACKAGES
        PACKAGES = await load_packages()
        
        await update.message.reply_text(f"✅ Berhasil menyimpan Pricelist:\n📦 **{poin} Koin** seharga **{rupiah(harga)}**", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/pricelist harga|poin`\nContoh: `/pricelist 15000|100`", parse_mode="Markdown")

async def admin_delete_pricelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        poin = int(context.args[0])
        result = await pricing_col.delete_one({"points": poin, "type": "standard"})
        
        if result.deleted_count > 0:
            global PACKAGES
            PACKAGES = await load_packages()
            await update.message.reply_text(f"✅ Pricelist untuk paket **{poin} Koin** berhasil dihapus.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ Paket dengan **{poin} Koin** tidak ditemukan.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/delete_pricelist <jumlah_poin>`\nContoh: `/delete_pricelist 100`", parse_mode="Markdown")

async def admin_change_priceunlimited(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        harga = int(context.args[0])
        await pricing_col.update_one(
            {"type": "unlimited"},
            {"$set": {"price": harga, "points": "unlimited", "type": "unlimited"}},
            upsert=True
        )
        
        global PACKAGES
        PACKAGES = await load_packages()
        await update.message.reply_text(f"✅ Berhasil mengubah harga paket **UNLIMITED** menjadi **{rupiah(harga)}**.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/change_priceunlimited <harga>`\nContoh: `/change_priceunlimited 149000`", parse_mode="Markdown")



# ==========================================
# WORKER BROADCAST LATAR BELAKANG
# ==========================================
async def run_broadcast_task(bot, admin_chat_id, target_msg_id, text, reply_to, users):
    sukses, gagal = 0, 0
    total = len(users)
    
    for u in users:
        try:
            if reply_to:
                await bot.copy_message(chat_id=u["user_id"], from_chat_id=admin_chat_id, message_id=reply_to.message_id)
            else:
                await bot.send_message(chat_id=u["user_id"], text=text)
            sukses += 1
        except Exception:
            gagal += 1
            
        # Sangat penting: Memberi jeda agar Telegram tidak kena FloodWait 
        # dan memberi kesempatan bot memproses perintah user lain
        await asyncio.sleep(0.05) 
        
    # Update pesan awal ke admin setelah seluruh iterasi selesai
    try:
        await bot.edit_message_text(
            chat_id=admin_chat_id,
            message_id=target_msg_id,
            text=f"✅ *Broadcast Selesai!*\n\n👥 Total Target: {total}\n✅ Berhasil: {sukses}\n❌ Gagal: {gagal}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"[-] Gagal mengupdate status pesan broadcast: {e}")


# ==========================================
# HANDLER UTAMA COMMAND /BROADCAST
# ==========================================
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    
    reply_to = update.message.reply_to_message
    text = " ".join(context.args) if context.args else None
    
    if not reply_to and not text:
        await update.message.reply_text("⚠️ *Cara Penggunaan:*\nGunakan `/broadcast <teks pesan>` atau balas (reply) sebuah pesan/gambar/video dengan mengetik `/broadcast`.", parse_mode="Markdown")
        return
        
    # Ambil data pengguna
    users = await users_col.find({}).to_list(length=None)
    total = len(users)
    
    msg = await update.message.reply_text(f"⏳ *Memulai Broadcast ke {total} member di latar belakang...*\n\n_Anda dapat terus menggunakan bot tanpa halangan. Notifikasi akan diperbarui jika sudah selesai._", parse_mode="Markdown")
    
    # Eksekusi loop pengiriman di luar handler ini (Background Task)
    asyncio.create_task(run_broadcast_task(
        bot=context.bot,
        admin_chat_id=update.effective_chat.id,
        target_msg_id=msg.message_id,
        text=text,
        reply_to=reply_to,
        users=users
    ))

async def admin_add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        poin = context.args[1]
        poin_val = "unlimited" if poin.lower() == "unlimited" else int(poin)
        
        await get_or_create_user(target_id, "MemberBaru") # Pastikan user ada di DB
        await users_col.update_one({"user_id": target_id}, {"$set": {"points": poin_val}})
        
        await update.message.reply_text(f"✅ Berhasil set poin user `{target_id}` menjadi **{poin_val}**.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/add_member <chat_id> <jumlah/unlimited>`", parse_mode="Markdown")

async def admin_add_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        bonus = int(context.args[1])
        await add_points(target_id, bonus)
        await update.message.reply_text(f"✅ Berhasil menambahkan bonus **{bonus} koin** ke user `{target_id}`.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/add_bonus <chat_id> <jumlah>`", parse_mode="Markdown")

async def admin_delete_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        result = await users_col.delete_one({"user_id": target_id})
        if result.deleted_count > 0:
            await update.message.reply_text(f"✅ User `{target_id}` berhasil dihapus dari database.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ User `{target_id}` tidak ditemukan.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Format salah! Gunakan: `/delete_member <chat_id>`", parse_mode="Markdown")

async def admin_list_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    
    msg = await update.message.reply_text("⏳ *Sedang mengekstrak data member...*", parse_mode="Markdown")
    
    try:
        # Mengambil seluruh data member dari database
        users = await users_col.find({}).to_list(length=None)
        total = len(users)
        
        if total == 0:
            await msg.edit_text("⚠️ Tidak ada data member di database.")
            return
            
        # MongoDB menggunakan ObjectId untuk '_id' yang tidak bisa di-serialize ke JSON secara default.
        # Kita ubah _id menjadi string terlebih dahulu.
        for u in users:
            if '_id' in u:
                u['_id'] = str(u['_id'])
                
        # Konversi list dictionary ke format JSON string yang rapi (indent=4)
        json_data = json.dumps(users, indent=4, ensure_ascii=False)
        
        # Buat file JSON di dalam memory (RAM) menggunakan BytesIO
        file_obj = io.BytesIO(json_data.encode('utf-8'))
        file_obj.name = f"Data_Member_{total}_Orang.json"
        
        # Kirim file document ke admin
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_obj,
            caption=f"📊 **Backup Data Member**\n👥 Total Member: `{total} Orang`",
            parse_mode="Markdown"
        )
        
        # Hapus pesan "sedang mengekstrak"
        await msg.delete()
        
    except Exception as e:
        await msg.edit_text(f"❌ *Gagal mengekstrak data:*\n`{str(e)}`", parse_mode="Markdown")

# ==========================================
async def admin_cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID: return
    text = "🛠️ *DAFTAR COMMAND ADMIN* 🛠️\n\n• `/add_member <chat_id> <jumlah/unlimited>`\n• `/add_bonus <chat_id> <jumlah>`\n• `/delete_member <chat_id>`\n• `/list_member`\n• `/broadcast <teks>` / balas pesan\n• `/success <kode_wd>`\n• `/check_komisi`\n• `/pricelist harga|poin`\n• `/delete_pricelist harga|poin`\n• `/change_priceunlimited <harga>`\n• `/cmd`"
    await update.message.reply_text(text, parse_mode="Markdown")

# [SELURUH IMPLEMENTASI FUNGSI ADMIN LAINNYA TETAP UTUH, DEMI KERINGKASAN PANDUAN TIDAK DIPERPANJANG DISINI]
# NOTE: Salin semua implementasi fitur admin seperti /add_member, /broadcast, dsb dari file aslinya ke bagian ini.

# ==========================================
# COMMAND & CALLBACK HANDLERS
# ==========================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query and update.message:
        try: await update.message.set_reaction(reaction="🎉")
        except: pass
    if not query:
        try:
            temp_msg = await update.message.reply_text("🔄", reply_markup=ReplyKeyboardRemove())
            await temp_msg.delete()
            if update.message.text and update.message.text.startswith('/'):
                await update.message.delete()
        except Exception: pass
        chat_id = update.effective_chat.id
        username = update.effective_user.username or "TanpaUsername"
    else:
        chat_id = query.message.chat_id
        username = query.from_user.username or "TanpaUsername"
        
    user_data, is_new_user = await get_or_create_user(chat_id, username)
    
    if not query and context.args and context.args[0].startswith("aff_"):
        try:
            inviter_id = int(context.args[0].split("_")[1])
            await register_referral(inviter_id, chat_id, context.bot)
        except Exception: pass

    if is_new_user and not query:
        intro_text = (
            f"✨ *Selamat Datang di {BOT_NAME} !* ✨\n\n"
            f"{BOT_NAME} adalah asisten pintar yang dilengkapi dengan berbagai fitur AI canggih:\n\n"
            "🎨 *Image Generation*\n"
            "Buat dan edit gambar menakjubkan menggunakan teknologi AI.\n\n"
            "🎥 *Video Generation*\n"
            "Sulap teks atau gambar statis menjadi video berkualitas tinggi.\n\n"
            "🕺 *Motion Control*\n"
            "Gerakkan wajah atau tubuh dari sebuah foto menjadi video animasi yang hidup.\n\n"
            "👇 _Klik tombol di bawah ini jika kamu tertarik untuk mencoba!_"
        )
        keyboard = ReplyKeyboardMarkup([["Saya Tertarik"]], resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(chat_id=chat_id, text=intro_text, reply_markup=keyboard, parse_mode="Markdown")
        return WAITING_INTERESTED
    
    pts = user_data.get('points', 0)
    total_gen = user_data.get('total_generates', 0)
    
    str_pts = "UNLIMITED 👑" if chat_id == ADMIN_ID else ("UNLIMITED ♾️" if pts == "unlimited" else f"{pts} Koin")
    status_user = "Admin 👑" if chat_id == ADMIN_ID else "Member 👤"
        
    res_gen = await users_col.aggregate([{"$group": {"_id": None, "total": {"$sum": "$total_generates"}}}]).to_list(length=None)
    total_users = await users_col.count_documents({})
    total_gen_all = res_gen[0]["total"] if res_gen else 0
    
    welcome_msg = f"⚡ <b>{BOT_NAME}</b> ⚡\n\n📅 <i>{get_now_jkt()}</i>\n\n👤 <b>Informasi Akun</b>\n┣ 🆔 ID : <code>{chat_id}</code>\n┣ 👤 Username : @{username}\n┣ 🔰 Status : <b>{status_user}</b>\n┣ 🪙 Poin : <b>{str_pts}</b>\n┗ ✨ Total Generate : <code>{total_gen} Kali</code>\n\n📊 <b>Statistik Bot</b>\n┣ 👥 Total Pengunjung : <code>{total_users} Orang</code>\n┗ 🚀 Total Generate Selesai : <code>{total_gen_all} Kali</code>\n\n👇 <i>Silakan pilih kategori di bawah ini:</i>"
    await send_new_menu(update, context, welcome_msg, get_main_keyboard(), "HTML")
    return CHOOSING_FEATURE

async def handle_buy_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await users_col.find_one({"user_id": chat_id})
    if user and user.get("points") == "unlimited":
        await send_new_menu(update, context, "⛔ **Anda sudah memiliki paket UNLIMITED!**\nAnda tidak perlu membeli koin lagi.", parse_mode="Markdown")
        return CHOOSING_FEATURE
        
    text = "💳 **Pilih Paket Koin/Poin yang ingin dibeli:**\n\n_Pembayaran diproses otomatis via QRIS. Koin akan langsung masuk setelah lunas._"
    global PACKAGES
    PACKAGES = await load_packages()
    
    keyboard = []
    for pkg_key, pkg in PACKAGES.items():
        btn_text = f"👑 {pkg['name']} - {rupiah(pkg['price'])}" if pkg['points'] == 'unlimited' else f"🪙 {pkg['name']} - {rupiah(pkg['price'])}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy_{pkg_key}")])

    if not keyboard:
        await send_new_menu(update, context, "⚠️ _Sistem top-up sedang dalam pemeliharaan (Tidak ada list harga)._", parse_mode="Markdown")
        return CHOOSING_FEATURE

    keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")])
    await send_new_menu(update, context, text, InlineKeyboardMarkup(keyboard), "Markdown")
    return CHOOSING_FEATURE

async def process_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    pkg_key = query.data.replace("buy_", "")
    
    user = await users_col.find_one({"user_id": chat_id})
    if user and user.get("points") == "unlimited":
        await context.bot.send_message(chat_id, "⛔ **Anda sudah memiliki paket UNLIMITED!**", parse_mode="Markdown")
        return
    
    pending = await orders_col.find_one({"chat_id": chat_id, "status": "pending"})
    if pending:
        await context.bot.send_message(chat_id, "⚠️ **Selesaikan atau batalkan pesanan Anda sebelumnya!**", parse_mode="Markdown")
        return

    global PACKAGES
    PACKAGES = await load_packages() 
    if pkg_key not in PACKAGES:
        await context.bot.send_message(chat_id, "⚠️ **Paket tidak ditemukan!**\n_Harga mungkin telah diupdate, silakan buka ulang menu Beli Poin._", parse_mode="Markdown")
        return

    pkg = PACKAGES[pkg_key]
    success, order_id, payment, err = await asyncio.to_thread(create_payment, pkg["price"], PROJECT, API_KEY)
    
    if not success:
        await context.bot.send_message(chat_id, f"❌ Gagal membuat pembayaran: {err}")
        return
        
    try: await query.message.delete()
    except: pass

    msg = await context.bot.send_photo(
        chat_id=chat_id,
        photo=generate_qr(payment),
        caption=f"💳 **Menunggu Pembayaran QRIS**\n\n📦 **Paket** : {pkg['name']}\n🧾 **Order ID** : `{order_id}`\n💰 **Tagihan** : `{rupiah(pkg['price'])}`\n\n⏳ _Silakan scan QRIS di atas. Batas waktu: 5 Menit_",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batalkan Pesanan", callback_data=f"cancel_{order_id}")]]),
        parse_mode="Markdown"
    )

    order_doc = {
        "order_id": order_id, "chat_id": chat_id, "amount": pkg["price"], "pkg_key": pkg_key,
        "msg_id": msg.message_id, "status": "pending", "created_at": time.time()
    }
    await orders_col.insert_one(order_doc)
    asyncio.create_task(cek_pembayaran_loop(context, order_doc))

async def process_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.replace("cancel_", "")
    
    order = await orders_col.find_one({"order_id": order_id, "status": "pending"})
    if order:
        await asyncio.to_thread(cancel_payment, order["amount"], order_id, PROJECT, API_KEY)
        await orders_col.delete_one({"order_id": order_id})
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(query.message.chat_id, "❌ **Pesanan berhasil dibatalkan.**", parse_mode="Markdown")
    else:
        await context.bot.send_message(query.message.chat_id, "⚠️ Pesanan sudah tidak aktif.")

async def handle_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tutorial_text = (
        f"📚 *PANDUAN PENGGUNAAN {BOT_NAME} *\n\n"
        "🎨 *IMAGE GENERATION*\n"
        "• Pilih menu Image Generation ➔ Kirim 1 foto ➔ Masukkan prompt untuk di-generate.\n\n"
        "🎥 *VIDEO GENERATION*\n"
        "• *Text to Video:* Pilih jumlah ➔ Pilih rasio ➔ Pilih Model AI ➔ Masukkan prompt.\n"
        "• *Image to Video:* Pilih jumlah ➔ Pilih Model AI ➔ Kirim foto referensi ➔ Masukkan prompt.\n\n"
        "🕺 *MOTION CONTROL*\n"
        "• Pilih menu ➔ Kirim 1 foto wajah/orang ➔ Kirim URL video gerak dari TikTok.\n\n"
        "💡 *Tips Optimal:*\n"
        "_Gunakan prompt yang baik pada saat memasukkan prompt agar AI dapat memahami instruksi Anda dengan lebih detail dan akurat._"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]])
    await send_new_menu(update, context, tutorial_text, markup, "Markdown")
    return CHOOSING_FEATURE

# [SISA HELPER LEADERBOARD/AFFILIATE TETAP SAMA]
async def handle_task_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    tasks = ongoing_tasks.get(chat_id, {})
    markup_buttons = []

    if not tasks: 
        msg = "📋 *Tidak ada task yang sedang berjalan.*"
    else:
        msg = f"📋 *ACTIVE TASKS ({len(tasks)})*\n\n"
        for t_id, t_info in tasks.items(): 
            # Membersihkan karakter '_' agar tidak merusak format Markdown Telegram
            tipe_task = t_info.get('type', 'Unknown').replace('_', ' ').upper()
            msg += f"• ID: `{t_id}` | Type: {tipe_task}\n"
            
            # Tambahkan tombol cancel untuk tiap task
            markup_buttons.append([InlineKeyboardButton(f"❌ Batalkan Task {t_id}", callback_data=f"deltask_{t_id}")])
            
    markup_buttons.append([InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")])
    markup = InlineKeyboardMarkup(markup_buttons)
    
    await send_new_menu(update, context, msg, markup, "Markdown")
    return CHOOSING_FEATURE


async def handle_cancel_specific_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    task_id = query.data.replace("deltask_", "")

    if chat_id in ongoing_tasks and task_id in ongoing_tasks[chat_id]:
        task_info = ongoing_tasks[chat_id][task_id]
        f_type = task_info.get('type', 'image_gen')
        cost = COSTS.get(f_type, 15)

        # Hapus task dari dictionary ongoing dan database
        del ongoing_tasks[chat_id][task_id]
        if tasks_col is not None:
            await tasks_col.delete_one({"task_id": task_id})

        # Refund poin jika user bukan admin
        if chat_id != ADMIN_ID:
            await add_points(chat_id, cost)
            
            # --- TAMBAHAN: Refund Limit Harian Motion ---
            if f_type == "motion":
                user = await users_col.find_one({"user_id": chat_id})
                if user and user.get("points") != "unlimited":
                    await users_col.update_one({"user_id": chat_id}, {"$inc": {"motion_count_today": -1}})
            # --------------------------------------------
            
            teks_refund = f"\n_Poin {cost} Koin & Limit telah dikembalikan._"
        else:
            teks_refund = ""

        try: 
            await context.bot.send_message(chat_id, f"✅ *Task {task_id} berhasil dibatalkan!*{teks_refund}", parse_mode="Markdown")
        except: 
            pass

        # Refresh tampilan Task List
        return await handle_task_list(update, context)
    else:
        await query.answer("⚠️ Task tidak ditemukan atau sudah selesai.", show_alert=True)
        return CHOOSING_FEATURE 

# ==========================================
# GENERATION LOGIC
# ==========================================
async def send_task_log(bot, task_data: dict, result_url: str):
    try:
        current_time = get_now_jkt()
        task_type_str = {"image_gen": "Image Generation", "t2v": "Text To Video", "i2v": "Image To Video", "motion": "Motion Control"}.get(task_data.get('feature_type'), "Unknown Task")
        model_str = str(task_data.get('model_choice', 'nano-banana-pro')).upper()
        
        log_text = (
            " TASK SUCCESS LOG\n"
            f" Task: {task_type_str}\n"
            f" Model: {model_str}\n"
            f" Chat ID: {task_data.get('chat_id', 'N/A')}\n"
            f" Task ID: {task_data.get('task_id', 'N/A')}\n"
            f" Processing Time: {task_data.get('processing_time', 'N/A')}\n"
            f" System Time: {current_time}\n\n"
            f" Result: {result_url}"
        )
        await bot.send_message(chat_id=LOG_CHANNEL, text=log_text)
    except Exception as e: print(f"Log Error: {e}")

async def safe_status_update(context, chat_id, message_id, text, p_mode="Markdown"):
    try: await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode=p_mode, disable_web_page_preview=True)
    except:
        try: await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=p_mode, disable_web_page_preview=True)
        except: pass

async def background_generate_task(chat_id: int, status_msg_id: int, context: ContextTypes.DEFAULT_TYPE, task_data: dict):
    # MEMBATASI KONKURENSI SECARA GLOBAL AGAR SERVER TIDAK OOM
    async with GLOBAL_TASK_SEMAPHORE:
        start_time = time.time()
        task_id = task_data['task_id']
        f_type = task_data.get('feature_type')
        prompt = task_data['prompt']
        cost = COSTS.get(f_type, 15)
        
        # BACA FILE DARI DISK HANYA SAAT MULAI DIEKSEKUSI
        if 'img_path' in task_data and os.path.exists(task_data['img_path']):
            async with aiofiles.open(task_data['img_path'], 'rb') as f:
                task_data['img_bytes'] = await f.read()
                
        if 'images' in task_data:
            for img_dict in task_data['images']:
                if 'path' in img_dict and os.path.exists(img_dict['path']):
                    async with aiofiles.open(img_dict['path'], 'rb') as f:
                        img_dict['bytes'] = await f.read()
            
        try:
            if f_type == 'motion':
                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Uploading Photo & Extracting Video..._")
                
                uid, df_task_id = None, None
                for attempt in range(5):
                    if attempt > 0:
                        await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Retrying submit ke AI Motion (Percobaan {attempt+1}/5)..._")
                    try:
                        uid, df_task_id = await submit_motion_task(
                            task_data['img_bytes'], 
                            task_data['img_name'], 
                            task_data['tiktok_url'], 
                            replace_background=task_data.get('replace_background', False)
                        )
                        if uid and df_task_id: break 
                    except Exception as e:
                        print(f"[-] AI Motion Submit Error (Attempt {attempt+1}): {e}")
                    await asyncio.sleep(3)
                    
                if not uid or not df_task_id: 
                    raise Exception("Gagal submit task ke AI Motion setelah 5 kali percobaan.")
                    
                if tasks_col is not None:
                    await tasks_col.insert_one({"task_id": task_id, "chat_id": chat_id, "uid": uid, "feature_type": f_type, "model_choice": "KLING MOTION PRO", "status_msg_id": status_msg_id, "start_time": start_time, "username": task_data.get('username', 'Unknown'), "prompt": task_data['tiktok_url'], "queue_id": df_task_id, "createdAt": datetime.now(timezone.utc)})
                    
                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Rendering Motion Video..._")
                status, result_url = await poll_motion_task(uid, df_task_id, start_time)
                
            elif f_type == 'image_gen':
                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Acquiring token..._")
                token = await asyncio.to_thread(get_video_token_sync)
                if not token: raise Exception("Gagal mendapat token AI.")
                
                if tasks_col is not None:
                    await tasks_col.insert_one({"task_id": task_id, "chat_id": chat_id, "access_token": token, "feature_type": f_type, "model_choice": 'nano-banana-pro', "status_msg_id": status_msg_id, "start_time": start_time, "username": task_data.get('username', 'Unknown'), "prompt": prompt, "createdAt": datetime.now(timezone.utc)})
                
                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Requesting Image Generation..._")
                
                # Menggunakan .get() agar jika T2I (tanpa gambar), nilai yang dilempar adalah None
                img_bytes = task_data.get('img_bytes')
                img_name = task_data.get('img_name')
                
                queue_id, err = await asyncio.to_thread(get_geminigen_image_sync, prompt, token, img_bytes, img_name)
                if not queue_id: raise Exception(err)
                
                if tasks_col is not None: await tasks_col.update_one({"task_id": task_id}, {"$set": {"queue_id": queue_id}})

                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Rendering Image..._")
                status, result_url = await poll_geminigen_task(queue_id, token, is_image=True)

            elif f_type in ['i2v', 't2v'] and task_data['model_choice'] in ['veo_fast', 'veo_lite', 'grok']:
                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Acquiring token..._")
                token = await asyncio.to_thread(get_video_token_sync)
                if not token: raise Exception("Gagal mendapat token AI.")
                
                if tasks_col is not None:
                    await tasks_col.insert_one({"task_id": task_id, "chat_id": chat_id, "access_token": token, "feature_type": f_type, "model_choice": task_data['model_choice'], "status_msg_id": status_msg_id, "start_time": start_time, "username": task_data.get('username', 'Unknown'), "prompt": prompt, "createdAt": datetime.now(timezone.utc)})
                
                images_to_send = []
                if f_type == 'i2v':
                    if task_data['model_choice'] in ['veo_fast', 'veo_lite']: 
                        images_to_send = task_data.get('images', []) if task_data.get('veo_mode') == 'frame' else [{'bytes': task_data['img_bytes'], 'name': task_data['img_name']}]
                    elif task_data['model_choice'] == 'grok': 
                        images_to_send = task_data.get('images', [])

                ratio_to_send = task_data.get('video_ratio') if f_type == 'i2v' else task_data.get('ratio', '16:9')
                if task_data['model_choice'] == 'grok' and f_type == 't2v':
                    ratio_to_send = "portrait" if ratio_to_send in ["9:16", "3:4"] else "landscape"

                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Requesting {task_data['model_choice'].upper()}..._")
                queue_id, err = await asyncio.to_thread(get_geminigen_task_sync, prompt, token, images_to_send, task_data['model_choice'], ratio_to_send, task_data.get('veo_mode'))
                if not queue_id: raise Exception(err)
                
                if tasks_col is not None: await tasks_col.update_one({"task_id": task_id}, {"$set": {"queue_id": queue_id}})

                await safe_status_update(context, chat_id, status_msg_id, f"⏳ *[Task {task_id}]*\n_Rendering video..._")
                status, result_url = await poll_geminigen_task(queue_id, token, is_image=False)

            if status == "success":
                if chat_id not in ongoing_tasks or task_id not in ongoing_tasks.get(chat_id, {}):
                    return # Berhenti jika user sudah membatalkannya di Task List
                m, s = divmod(int(time.time() - start_time), 60)
                task_data['processing_time'] = f"{m} min {s} sec" if m > 0 else f"{s} sec"
                
                await send_task_log(context.bot, task_data, result_url) 
                await users_col.update_one({"user_id": chat_id}, {"$inc": {"total_generates": 1}})
                
                task_title = {"image_gen": "Image Generation", "t2v": "Text To Video", "i2v": "Image To Video", "motion": "Motion Control"}.get(f_type, "Task")
                msg = f"✅ <b>{task_title} Successfully Generated!</b>\n\n🤖 <b>Model:</b> {task_data.get('model_choice', 'NanoBanana2').upper()}\n⏱ <b>Processing Time:</b> {task_data['processing_time']}\n\n🔗 <b>Result Link:</b>\n<tg-spoiler>{result_url}</tg-spoiler>"
                try: await context.bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
                except: pass
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    
            elif status == "failed": raise Exception(result_url or "Server blocked the prompt.")
            else: raise Exception("Process Timeout.")

        except Exception as e:
            print(f"[ERROR] Task Failed: {e}")
            safe_error = str(e).replace("<", "&lt;").replace(">", "&gt;") 
            if chat_id != ADMIN_ID:
                await add_points(chat_id, cost)
                
                # --- TAMBAHAN: Refund Limit Harian Motion jika Gagal ---
                if f_type == "motion":
                    user = await users_col.find_one({"user_id": chat_id})
                    if user and user.get("points") != "unlimited":
                        await users_col.update_one({"user_id": chat_id}, {"$inc": {"motion_count_today": -1}})
                # -------------------------------------------------------

                fail_msg = f"❌ <b>[Task {task_id}] Failed:</b> {safe_error}\n\n<i>Poin {cost} Koin Anda (serta limit) telah dikembalikan.</i>"
            else: 
                fail_msg = f"❌ <b>[Task {task_id}] Failed:</b> {safe_error}"
                
            await safe_status_update(context, chat_id, status_msg_id, fail_msg, p_mode="HTML")
            cleanup_temp_files(task_data)
            if chat_id in ongoing_tasks and task_id in ongoing_tasks[chat_id]: del ongoing_tasks[chat_id][task_id]
            if tasks_col is not None:
                try: await tasks_col.delete_one({"task_id": task_id})
                except: pass

# ==========================================
# CONVERSATION HANDLERS
# ==========================================
async def handle_feature_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "menu_image":
        keyboard = [
            [InlineKeyboardButton("✍️ Text to Image", callback_data="feat_img_t2i"), 
             InlineKeyboardButton("📸 Image to Image", callback_data="feat_img_i2i")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        await send_new_menu(update, context, "🎨 *IMAGE GENERATION*\n_Silakan pilih mode di bawah ini:_ 👇", InlineKeyboardMarkup(keyboard), "Markdown")
        return CHOOSING_FEATURE
    elif query.data == "menu_video": 
        await send_new_menu(update, context, "🎥 *VIDEO GENERATION*\n_Silakan pilih fitur di bawah ini:_ 👇", get_video_gen_keyboard(), "Markdown")
        return CHOOSING_FEATURE
    return CHOOSING_FEATURE

async def handle_feature_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    feat = update.callback_query.data.replace("feat_", "")
    
    # --- TAMBAHAN UNTUK T2I & I2I ---
    if feat == "img_t2i":
        context.user_data['feature_type'] = 'image_gen'
        context.user_data['image_mode'] = 't2i'
        context.user_data['quantity'] = 1
        context.user_data['model_choice'] = 'nano-banana-pro'
        await send_new_menu(update, context, "✍️ *Masukkan Prompt untuk Text to Image:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return WAITING_PROMPT
        
    if feat == "img_i2i":
        context.user_data['feature_type'] = 'image_gen'
        context.user_data['image_mode'] = 'i2i'
        context.user_data['quantity'] = 1
        await send_new_menu(update, context, "📸 *Kirim 1 Foto sebagai referensi:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return WAITING_IMAGE
    # --------------------------------

    if feat == "motion":
        if chat_id != ADMIN_ID:
            user_active_tasks = ongoing_tasks.get(chat_id, {})   
            is_motion_running = any(task_info.get("type") == "motion" for task_info in user_active_tasks.values())
            
            if is_motion_running:
                await send_new_menu(
                    update, context,
                    "⛔ *Harap Tunggu!*\n\nAnda masih memiliki task Motion yang sedang berjalan. Harap tunggu hingga proses sebelumnya selesai sebelum membuat task baru.", 
                    InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]),
                    "Markdown"
                )
                return CHOOSING_FEATURE
        
        context.user_data['feature_type'] = feat
        context.user_data['quantity'] = 1
        keyboard = [[InlineKeyboardButton("🔄 Tukar Avatar di Video", callback_data="mmode_swap")], [InlineKeyboardButton("🕺 Tambahkan Gerakan ke Foto", callback_data="mmode_move")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
        await send_new_menu(update, context, "⚙️ *Pilih Mode Motion Control:*", InlineKeyboardMarkup(keyboard), "Markdown")
        return CHOOSING_MOTION_MODE
        
    context.user_data['feature_type'] = feat
    keyboard = [[InlineKeyboardButton("x1", callback_data="qty_1"), InlineKeyboardButton("x2", callback_data="qty_2"), InlineKeyboardButton("x3", callback_data="qty_3")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
    await send_new_menu(update, context, "🔢 *Select Generation Quantity:*", InlineKeyboardMarkup(keyboard), "Markdown")
    return CHOOSING_QUANTITY

async def handle_motion_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data
    context.user_data['replace_background'] = True if mode == "mmode_swap" else False
    await send_new_menu(update, context, "📸 *Kirim 1 Foto Wajah/Orang yang jelas:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
    return WAITING_MOTION_IMAGE

async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['quantity'] = int(update.callback_query.data.replace("qty_", ""))
    f_type = context.user_data['feature_type']
    
    if f_type == "t2v":
        keyboard = [
            [InlineKeyboardButton("9:16 (Portrait)", callback_data="ratio_9:16"), InlineKeyboardButton("16:9 (Landscape)", callback_data="ratio_16:9")], 
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        await send_new_menu(update, context, "📐 *Select Aspect Ratio:*", InlineKeyboardMarkup(keyboard), "Markdown")
        return CHOOSING_RATIO
    elif f_type == "i2v":
        keyboard = [
            [InlineKeyboardButton("Google Veo 3.1 Fast", callback_data="model_veo_fast"), InlineKeyboardButton("Google Veo 3.1 Lite", callback_data="model_veo_lite")], 
            [InlineKeyboardButton("XAI Grok", callback_data="model_grok")], 
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        await send_new_menu(update, context, "🎬 *Select the Video AI Model:*", InlineKeyboardMarkup(keyboard), "Markdown")
        return CHOOSING_MODEL

async def handle_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ratio'] = update.callback_query.data.replace("ratio_", "")
    f_type = context.user_data['feature_type']
    
    if f_type == "t2v":
        keyboard = [
            [InlineKeyboardButton("Google Veo 3.1 Fast", callback_data="model_veo_fast"), InlineKeyboardButton("Google Veo 3.1 Lite", callback_data="model_veo_lite")], 
            [InlineKeyboardButton("XAI Grok", callback_data="model_grok"), InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        await send_new_menu(update, context, "🎬 *Select the Video AI Model:*", InlineKeyboardMarkup(keyboard), "Markdown")
        return CHOOSING_MODEL

async def handle_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    model = update.callback_query.data.replace("model_", "")
    context.user_data['model_choice'] = model
    f_type = context.user_data['feature_type']
    
    if f_type == "t2v":
        if model in ["veo_fast", "veo_lite", "grok"]:
            await send_new_menu(update, context, "✍️ *Enter your Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
            return WAITING_PROMPT
            
    elif f_type == "i2v":
        if model in ['veo_fast', 'veo_lite', 'grok']:
            await send_new_menu(update, context, "📐 *Select Video Aspect Ratio:*", InlineKeyboardMarkup([[InlineKeyboardButton("9:16 (Vertical)", callback_data="vratio_9:16"), InlineKeyboardButton("16:9 (Horizontal)", callback_data="vratio_16:9")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
            return CHOOSING_VIDEO_RATIO

async def handle_video_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vratio = update.callback_query.data.replace("vratio_", "")
    model = context.user_data['model_choice']
    if model in ["veo_fast", "veo_lite"]: 
        context.user_data['video_ratio'] = vratio
        await send_new_menu(update, context, "⚙️ *Pilih Mode Input Video Veo:*", InlineKeyboardMarkup([[InlineKeyboardButton("Aset", callback_data="vmode_aset"), InlineKeyboardButton("Frame", callback_data="vmode_frame")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return CHOOSING_VEO_MODE
    elif model == "grok": 
        context.user_data['video_ratio'] = "portrait" if vratio == "9:16" else "landscape"
        context.user_data['images'] = []
        await send_new_menu(update, context, "📸 *Kirim 1 hingga 3 foto.*\nKlik '✅ Selesai Upload' jika sudah.", InlineKeyboardMarkup([[InlineKeyboardButton("✅ Selesai Upload", callback_data="upload_done")], [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return WAITING_GROK_IMAGES
    return CHOOSING_VIDEO_RATIO

async def handle_veo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.callback_query.data.replace("vmode_", "")
    context.user_data['veo_mode'] = mode
    if mode == "aset": await send_new_menu(update, context, "📸 *Kirim 1 Foto (Aset):*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
    else:
        context.user_data['images'] = []
        await send_new_menu(update, context, "📸 *Kirim Foto untuk First Frame:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
    return WAITING_IMAGE

# =========================================================================
# GANTI FUNGSI handle_image LAMA DI main.py DENGAN YANG DI BAWAH INI
# =========================================================================
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if update.message:
            try: await update.message.set_reaction(reaction="👀")
            except: pass
            
        file_obj = await (update.message.document.get_file() if update.message.document else update.message.photo[-1].get_file())
        img_name = update.message.document.file_name if update.message.document else f"{uuid.uuid4().hex[:8]}.jpg"
        temp_path = os.path.join(os.getcwd(), img_name)
        
        # 1. Unduh file ke server sementara
        await file_obj.download_to_drive(custom_path=temp_path)
        
        # ===============================================================
        # [TAMBAHAN BARU] VALIDASI GAMBAR AGAR REFERENSI SESUAI
        # ===============================================================
        try:
            # Membuka gambar dan memverifikasi integritasnya
            with Image.open(temp_path) as img:
                img.verify() # Mengecek apakah file korup/rusak secara internal
            
            # Membuka kembali untuk memastikan bisa di-load penuh (antisipasi corrupt parsial)
            with Image.open(temp_path) as img:
                img.load() 
                
            print(f"[+] Validasi Gambar Sukses: {img_name}")
            
        except Exception as img_err:
            # Jika validasi gagal, hapus file yang rusak dan suruh user kirim ulang
            print(f"[-] Validasi Gambar Gagal: {img_name} - Error: {img_err}")
            if os.path.exists(temp_path): os.remove(temp_path)
            
            if update.message:
                try: await update.message.set_reaction(reaction="😡")
                except: pass
            
            await context.bot.send_message(
                chat_id=chat_id, 
                text="❌ **File gambar rusak, korup, atau tidak didukung!**\n\nSistem gagal memverifikasi file tersebut sebagai referensi. Silakan kirim file gambar lain yang valid (JPG/PNG).", 
                parse_mode="Markdown"
            )
            return WAITING_IMAGE
        # ===============================================================
        
        f_type = context.user_data.get('feature_type')
        model = context.user_data.get('model_choice')
        veo_mode = context.user_data.get('veo_mode')
        
        # Lanjutkan logika aslinya jika lolos validasi
        if f_type == "image_gen":
            context.user_data['img_path'] = temp_path
            context.user_data['img_name'] = img_name
            context.user_data['model_choice'] = 'nano-banana-pro'
            await send_new_menu(update, context, "✍️ *Masukkan Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
            return WAITING_PROMPT
            
        elif f_type == "i2v" and model in ['veo_fast', 'veo_lite'] and veo_mode == 'frame':
            if 'images' not in context.user_data: context.user_data['images'] = []
            context.user_data['images'].append({'path': temp_path, 'name': img_name})
            
            if len(context.user_data['images']) == 1:
                await send_new_menu(update, context, "📸 *Kirim Foto untuk Last Frame:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
                return WAITING_IMAGE
            else:
                await send_new_menu(update, context, "✍️ *Masukkan Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
                return WAITING_PROMPT
        else:
            # Mode Aset, T2V, dll
            context.user_data['img_path'] = temp_path
            context.user_data['img_name'] = img_name
            await send_new_menu(update, context, "✍️ *Enter your Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
            return WAITING_PROMPT
            
    except Exception as e:
        print(f"[handle_image error] {e}")
        # Jika terjadi error tak terduga saat proses, pastikan file sementara di hapus jika ada
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return WAITING_IMAGE

async def handle_grok_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data == "upload_done":
        if not context.user_data.get('images'): return WAITING_GROK_IMAGES
        await send_new_menu(update, context, "✍️ *Enter your Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return WAITING_PROMPT
    try:
        file_obj = await (update.message.document.get_file() if update.message.document else update.message.photo[-1].get_file())
        img_name = update.message.document.file_name if update.message.document else f"{uuid.uuid4().hex[:8]}.jpg"
        temp_path = os.path.join(os.getcwd(), img_name)
        await file_obj.download_to_drive(custom_path=temp_path)
        
        if 'images' not in context.user_data: context.user_data['images'] = []
        context.user_data['images'].append({"path": temp_path, "name": img_name})
        
        img_count = len(context.user_data['images'])
        if img_count >= 3:
            await send_new_menu(update, context, "✅ *Maksimal 3 foto telah diunggah.*\n\n✍️ *Enter your Prompt:*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
            return WAITING_PROMPT
        else:
            await update.message.reply_text(f"📥 Foto #{img_count} diterima. Kirim lagi atau klik Selesai di atas.")
            return WAITING_GROK_IMAGES
    except: return WAITING_GROK_IMAGES

async def handle_motion_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file_obj = await (update.message.document.get_file() if update.message.document else update.message.photo[-1].get_file())
        img_name = update.message.document.file_name if update.message.document else f"{uuid.uuid4().hex[:8]}.jpg"
        temp_path = os.path.join(os.getcwd(), img_name)
        await file_obj.download_to_drive(custom_path=temp_path)
        
        context.user_data['img_path'] = temp_path
        context.user_data['img_name'] = img_name
        
        await send_new_menu(update, context, "🔗 *Kirim URL Video Referensi (TikTok):*", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]), "Markdown")
        return WAITING_MOTION_URL
    except:
        return WAITING_MOTION_IMAGE

async def handle_motion_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass

    tiktok_url = update.message.text
    f_type = "motion"
    cost_per_gen = COSTS.get(f_type, 40)
    
    if chat_id != ADMIN_ID:
        user = await users_col.find_one({"user_id": chat_id})
        pts = user.get("points", 0) if user else 0
            
        if pts != "unlimited":
            try: current_points = int(pts)
            except: current_points = 0
            
            # --- LOGIKA LIMIT HARIAN MOTION (10X PER HARI) ---
            now = datetime.now(JKT)
            today_str = now.strftime('%Y-%m-%d')
            last_motion_date = user.get("last_motion_date", "")
            motion_count = user.get("motion_count_today", 0)
            
            # Jika hari sudah berganti, reset hitungan limit menjadi 0
            if last_motion_date != today_str:
                motion_count = 0
            
            if motion_count >= 10:
                await update.message.reply_text(
                    "⛔ *Limit Harian Tercapai!*\n\nAnda telah mencapai batas maksimal **10x generate Motion per hari** untuk pengguna reguler.\n\n_Upgrade ke paket UNLIMITED untuk generate tanpa batas!_", 
                    parse_mode="Markdown", 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]])
                )
                cleanup_temp_files(context.user_data)
                context.user_data.clear()
                return ConversationHandler.END
            # ------------------------------------------------

            if current_points < cost_per_gen:
                await update.message.reply_text(f"⛔ *Koin Tidak Mencukupi!*\n\nAnda membutuhkan `{cost_per_gen} Koin` untuk fitur Motion Control.\nSisa koin Anda: `{current_points}`\n\n_Silakan Topup Poin terlebih dahulu._", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]))
                cleanup_temp_files(context.user_data)
                context.user_data.clear()
                return ConversationHandler.END
            
            new_pts = current_points - cost_per_gen
            
            # Potong koin sekaligus tambah hitungan Motion hari ini
            if last_motion_date != today_str:
                await users_col.update_one({"user_id": chat_id}, {"$set": {"points": new_pts, "last_motion_date": today_str, "motion_count_today": 1}})
            else:
                await users_col.update_one({"user_id": chat_id}, {"$set": {"points": new_pts}, "$inc": {"motion_count_today": 1}})
            
        if len(ongoing_tasks.get(chat_id, {})) >= 5:
            await update.message.reply_text(f"⛔ *Queue Limit Reached!* Max 5 active tasks.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]))
            if pts != "unlimited": 
                # Kembalikan koin dan limit jika antrean penuh
                await users_col.update_one({"user_id": chat_id}, {"$set": {"points": current_points}, "$inc": {"motion_count_today": -1}})
            cleanup_temp_files(context.user_data)
            context.user_data.clear()
            return ConversationHandler.END

    context.user_data['tiktok_url'] = tiktok_url
    context.user_data['prompt'] = tiktok_url
    context.user_data['model_choice'] = "KLING MOTION PRO"
    context.user_data['chat_id'] = chat_id
    context.user_data['username'] = update.effective_user.username
    
    if chat_id not in ongoing_tasks: ongoing_tasks[chat_id] = {}
    
    await update.message.reply_text(f"🚀 *Starting Motion Control Task*\n👑 _Admin Bypass (Free)_" if chat_id == ADMIN_ID else f"🚀 *Starting Motion Control Task*\n🪙 _Biaya: {cost_per_gen} Koin_", parse_mode="Markdown")

    task_id = str(uuid.uuid4())[:8]
    ongoing_tasks[chat_id][task_id] = {"type": f_type, "prompt": tiktok_url}
    task_data = dict(context.user_data)
    task_data['task_id'] = task_id
    status_msg = await update.message.reply_text(f"⏳ *[Task 1/1] ID: {task_id}*\n_Connecting to AI..._", parse_mode="Markdown")
    
    asyncio.create_task(background_generate_task(chat_id, status_msg.message_id, context, task_data))
    
    context.user_data.clear()
    return ConversationHandler.END

async def process_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        try: await update.message.set_reaction(reaction="⚡")
        except Exception as e: pass
    chat_id = update.effective_chat.id
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass

    prompt = update.message.text
    quantity = context.user_data.get('quantity', 1)
    f_type = context.user_data.get('feature_type')
    cost_per_gen = COSTS.get(f_type, 15)
    total_cost = cost_per_gen * quantity
    
    if chat_id != ADMIN_ID:
        user = await users_col.find_one({"user_id": chat_id})
        pts = user.get("points", 0) if user else 0
        
        if pts != "unlimited":
            try: current_points = int(pts)
            except: current_points = 0
            
            if current_points < total_cost:
                await update.message.reply_text(f"⛔ *Koin Tidak Mencukupi!*\n\nAnda membutuhkan `{total_cost} Koin` untuk {quantity}x generate.\nSisa koin Anda: `{current_points}`\n\n_Silakan Topup Poin terlebih dahulu._", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]))
                cleanup_temp_files(context.user_data)
                context.user_data.clear()
                return ConversationHandler.END
            
            new_pts = current_points - total_cost
            await users_col.update_one({"user_id": chat_id}, {"$set": {"points": new_pts}})
            
        if len(ongoing_tasks.get(chat_id, {})) + quantity > 5:
            await update.message.reply_text(f"⛔ *Queue Limit Reached!* Max 5 active tasks.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]))
            if pts != "unlimited": 
                await users_col.update_one({"user_id": chat_id}, {"$set": {"points": current_points}})
            cleanup_temp_files(context.user_data)
            context.user_data.clear()
            return ConversationHandler.END

    context.user_data['prompt'], context.user_data['chat_id'], context.user_data['username'] = prompt, chat_id, update.effective_user.username
    if chat_id not in ongoing_tasks: ongoing_tasks[chat_id] = {}
    
    await update.message.reply_text(f"🚀 *Starting {quantity} Task(s)*\n👑 _Admin Bypass (Free)_" if chat_id == ADMIN_ID else f"🚀 *Starting {quantity} Task(s)*\n🪙 _Biaya: {total_cost} Koin_", parse_mode="Markdown")

    for i in range(quantity):
        task_id = str(uuid.uuid4())[:8]
        ongoing_tasks[chat_id][task_id] = {"type": f_type, "prompt": prompt}
        task_data = dict(context.user_data)
        task_data['task_id'] = task_id
        status_msg = await update.message.reply_text(f"⏳ *[Task {i+1}/{quantity}] ID: {task_id}*\n_Connecting to AI..._", parse_mode="Markdown")
        asyncio.create_task(background_generate_task(chat_id, status_msg.message_id, context, task_data))
        await asyncio.sleep(1) 
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cleanup_temp_files(context.user_data)
    
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass
    if update.callback_query:
        await update.callback_query.answer("❌ Aksi dibatalkan")
        msg = await context.bot.send_message(chat_id=chat_id, text="❌ *Aksi dibatalkan.* Mengembalikan ke menu utama...", parse_mode="Markdown")
        await asyncio.sleep(1.5)
        try: await msg.delete()
        except: pass
    context.user_data.clear()
    return await start_cmd(update, context)

async def handle_version_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    version_text = (
        "ℹ️ *INFORMASI VERSI APLIKASI*\n\n"
        "🔹 *Versi:* ALPHA19\n\n"
        "💰 *BIAYA KOIN (PER GENERATE)*\n"
        "┣ 🎨 Image Generation: `15 Koin`\n"
        "┣ 🎬 Text to Video: `15 Koin`\n"
        "┣ 🎞️ Image to Video: `30 Koin`\n"
        "┗ 🕺 Motion Control: `40 Koin`\n\n"
        "🤖 *MODEL AI TERSEDIA*\n"
        "*🎨 Image Generation:*\n"
        "• Nano Banana Pro\n\n"
        "*🎥 Video Generation:*\n"
        "• Google Veo 3.1 Fast\n"
        "• Google Veo 3.1 Lite\n"
        "• XAI Grok\n\n"
        "*🕺 Motion Control:*\n"
        "• KLING MOTION CONTROL PRO"
    )
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="main_menu")]])
    await send_new_menu(update, context, version_text, markup, "Markdown")
    return CHOOSING_FEATURE

async def error_handler_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[!] Terjadi Error Global: {context.error}")

# ==========================================
# MAIN APP
# ==========================================
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init_setup)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    
    app.add_error_handler(error_handler_global)
    
    app.add_handler(CallbackQueryHandler(process_buy_callback, pattern="^buy_pkg_"))
    app.add_handler(CallbackQueryHandler(process_cancel_callback, pattern="^cancel_"))
    # Register admin commands
    app.add_handler(CommandHandler('cmd', admin_cmd_list))
    app.add_handler(CommandHandler('broadcast', admin_broadcast))
    app.add_handler(CommandHandler('add_member', admin_add_member))
    app.add_handler(CommandHandler('add_bonus', admin_add_bonus))
    app.add_handler(CommandHandler('delete_member', admin_delete_member))
    app.add_handler(CommandHandler('list_member', admin_list_member))
    
    # --- TAMBAHKAN 5 BARIS INI ---
    app.add_handler(CommandHandler('success', admin_success_wd))
    app.add_handler(CommandHandler('check_komisi', admin_check_komisi))
    app.add_handler(CommandHandler('pricelist', admin_pricelist))
    app.add_handler(CommandHandler('delete_pricelist', admin_delete_pricelist))
    app.add_handler(CommandHandler('change_priceunlimited', admin_change_priceunlimited))
 
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start_cmd),
            CallbackQueryHandler(start_cmd, pattern="^main_menu$")
        ],
        states={
            CHOOSING_FEATURE: [
                # --- TAMBAHKAN KEDUA BARIS INI UNTUK TOMBOL TARIK ---
                CallbackQueryHandler(handle_tarik_komisi, pattern="^aff_tarik$"),
                CallbackQueryHandler(handle_tarik_locked, pattern="^aff_tarik_locked$"),
                #
                CallbackQueryHandler(handle_cancel_specific_task, pattern="^deltask_"), 
                CallbackQueryHandler(handle_feature_category, pattern="^(menu_image|menu_video)$"),
                CallbackQueryHandler(handle_feature_selection, pattern="^feat_"),
                CallbackQueryHandler(handle_buy_points, pattern="^menu_buy$"),
                CallbackQueryHandler(handle_task_list, pattern="^menu_task$"),
                CallbackQueryHandler(handle_affiliate_menu, pattern="^menu_affiliate$"),
                CallbackQueryHandler(handle_riwayat_wd, pattern="^aff_riwayat$"),
                CallbackQueryHandler(handle_tutorial, pattern="^menu_tutorial$"),
                CallbackQueryHandler(handle_version_info, pattern="^menu_version$"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            CHOOSING_MOTION_MODE: [
                CallbackQueryHandler(handle_motion_mode, pattern="^mmode_"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            CHOOSING_QUANTITY: [CallbackQueryHandler(handle_quantity, pattern="^qty_"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            CHOOSING_RATIO: [CallbackQueryHandler(handle_ratio, pattern="^ratio_"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            CHOOSING_MODEL: [CallbackQueryHandler(handle_model, pattern="^model_"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            CHOOSING_VIDEO_RATIO: [CallbackQueryHandler(handle_video_ratio, pattern="^vratio_"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            CHOOSING_VEO_MODE: [CallbackQueryHandler(handle_veo_mode, pattern="^vmode_"), CallbackQueryHandler(cancel, pattern="^cancel$")],
            WAITING_IMAGE: [
                MessageHandler((filters.PHOTO | filters.Document.IMAGE), handle_image),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_GROK_IMAGES: [
                MessageHandler((filters.PHOTO | filters.Document.IMAGE), handle_grok_images),
                CallbackQueryHandler(handle_grok_images, pattern="^upload_done$"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_MOTION_IMAGE: [
                MessageHandler((filters.PHOTO | filters.Document.IMAGE), handle_motion_image),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_MOTION_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_motion_url),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_prompt),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_INTERESTED: [
                MessageHandler(filters.Regex("(?i)^Saya Tertarik$"), start_cmd),
                CommandHandler('start', start_cmd)
            ],
            WAITING_WD_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wd_amount),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            WAITING_WD_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wd_info),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start_cmd),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CallbackQueryHandler(start_cmd, pattern="^main_menu$")
        ],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    
    while True:
        try:
            print(f"🚀 {BOT_NAME} AI is running! (Optimized with Motor + Semaphore + Aiofiles)")
            app.run_polling(drop_pending_updates=True, close_loop=False)
            break 
        except KeyboardInterrupt:
            print("[!] Bot dimatikan oleh user.")
            break
        except Exception as e:
            print(f"[-] Terjadi kesalahan koneksi fatal: {e}. Restarting dalam 1 detik...")
            time.sleep(1)

if __name__ == "__main__":
    main()