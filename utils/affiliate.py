import time
import uuid
import json
import os # Tambahkan di bagian atas file (bersama import lainnya)
import io
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Konfigurasi Collection
affiliates_col = None
withdrawals_col = None
users_col_ref = None

def init_affiliate_db(db):
    global affiliates_col, withdrawals_col, users_col_ref
    affiliates_col = db["affiliates"]
    withdrawals_col = db["withdrawals"]
    users_col_ref = db["users"]

def rupiah(n):
    return "Rp {:,}".format(int(n)).replace(",", ".")

def get_simple_time():
    return datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M:%S')

async def get_or_create_affiliate(user_id, username):
    # TAMBAH AWAIT UNTUK MOTOR ASYNC
    aff = await affiliates_col.find_one({"user_id": user_id})
    if not aff:
        aff = {
            "user_id": user_id,
            "username": username,
            "balance": 0,
            "total_commission": 0,
            "friends": []
        }
        await affiliates_col.insert_one(aff)
    else:
        # Update username jika berubah
        await affiliates_col.update_one({"user_id": user_id}, {"$set": {"username": username}})
    return aff

async def register_referral(inviter_id, new_user_id, bot):
    # Cek apakah user baru sudah ada inviter
    user = await users_col_ref.find_one({"user_id": new_user_id})
    if user and user.get("inviter_id"):
        return # Sudah pernah diundang orang lain

    if inviter_id == new_user_id:
        return # Tidak bisa mengundang diri sendiri
        
    # Set inviter_id ke user baru
    await users_col_ref.update_one({"user_id": new_user_id}, {"$set": {"inviter_id": inviter_id}})
    
    # Pastikan database affiliate pengundang terbentuk meski dia belum pernah klik menu
    inviter_user = await users_col_ref.find_one({"user_id": inviter_id})
    inv_username = inviter_user.get("username", "TanpaUsername") if inviter_user else "TanpaUsername"
    await get_or_create_affiliate(inviter_id, inv_username)
    
    # Tambahkan teman
    await affiliates_col.update_one({"user_id": inviter_id}, {"$addToSet": {"friends": new_user_id}})
    
    try:
        await bot.send_message(
            chat_id=inviter_id,
            text=f"🎉 **Pengguna Baru Bergabung!**\nSeseorang telah bergabung menggunakan tautan undangan kamu. Kamu akan mendapatkan komisi 30% setiap kali dia membeli poin!",
            parse_mode="Markdown"
        )
    except:
        pass

async def process_commission(buyer_id, buyer_username, amount, purchased_points, bot, log_channel):
    user = await users_col_ref.find_one({"user_id": buyer_id})
    if not user or not user.get("inviter_id"):
        return

    inviter_id = user["inviter_id"]
    
    # ==========================================
    # LOGIKA BONUS UNLIMITED UNTUK PENGUNDANG
    # ==========================================
    if purchased_points == "unlimited":
        inviter_user = await users_col_ref.find_one({"user_id": inviter_id})
        if inviter_user and inviter_user.get("points") != "unlimited":
            # Upgrade poin pengundang jadi unlimited
            await users_col_ref.update_one({"user_id": inviter_id}, {"$set": {"points": "unlimited"}})
            
            # Beri notifikasi ke pengundang
            try:
                await bot.send_message(
                    chat_id=inviter_id,
                    text="🎉 **BONUS SPESIAL!** 🎉\nTeman yang kamu undang baru saja membeli paket Unlimited. Sebagai bonus, **Poin kamu sekarang juga di-upgrade menjadi UNLIMITED!** ♾️👑",
                    parse_mode="Markdown"
                )
            except:
                pass
    # ==========================================

    # Proses komisi uang 30% tetap berjalan
    commission = int(amount * 0.3)
    
    # Pastikan database affiliate pengundang terbentuk
    inviter_user = await users_col_ref.find_one({"user_id": inviter_id})
    inv_username = inviter_user.get("username", "TanpaUsername") if inviter_user else "TanpaUsername"
    await get_or_create_affiliate(inviter_id, inv_username)
    
    # Berikan komisi ke balance
    await affiliates_col.update_one(
        {"user_id": inviter_id}, 
        {"$inc": {"balance": commission, "total_commission": commission}}
    )

    # Notifikasi Komisi Uang ke Pengundang
    try:
        await bot.send_message(
            chat_id=inviter_id,
            text=f"💰 **KOMISI MASUK!**\nTeman yang kamu undang baru saja melakukan pembelian.\n\n💵 Komisi: **{rupiah(commission)}**\nSilakan cek di menu Affiliate Program.",
            parse_mode="Markdown"
        )
    except:
        pass

    # Log ke channel @log_belipoin
    log_text = (
        f"💸 <b>LOG PEMBELIAN & KOMISI</b>\n\n"
        f"<b>PEMBELI:</b>\n"
        f"🆔 ID: <code>{buyer_id}</code>\n"
        f"👤 Username: @{buyer_username}\n"
        f"🛍️ Total Beli: {rupiah(amount)}\n\n"
        f"<b>PENGUNDANG (KOMISI 30%):</b>\n"
        f"🆔 ID: <code>{inviter_id}</code>\n"
        f"👤 Username: @{inv_username}\n"
        f"💰 Komisi Masuk: {rupiah(commission)}\n"
        f"⏰ Waktu: {get_simple_time()}"
    )
    try:
        await bot.send_message(chat_id=log_channel, text=log_text, parse_mode="HTML")
    except:
        pass

# ================= MENU & HANDLERS ================= #
def get_affiliate_keyboard(balance):
    keyboard = []
    # Nama tombol tetap sama, hanya callback_data yang membedakan logic
    if balance >= 5000:
        keyboard.append([InlineKeyboardButton("💸 Tarik Komisi", callback_data="aff_tarik")])
    else:
        keyboard.append([InlineKeyboardButton("💸 Tarik Komisi", callback_data="aff_tarik_locked")])
        
    keyboard.append([InlineKeyboardButton("📜 Riwayat Penarikan", callback_data="aff_riwayat")])
    keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

async def handle_affiliate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    
    if not user.username:
        await query.answer("⚠️ Anda harus mengatur Username Telegram (di Pengaturan Profil) terlebih dahulu!", show_alert=True)
        return

    aff_data = await get_or_create_affiliate(user.id, user.username)
    bot_username = context.bot.username
    ref_link = f"https://t.me/{bot_username}?start=aff_{user.id}"
    
    text = (
        "🤝 **AFFILIATE PROGRAM**\n\n"
        f"Bagikan link di bawah ini. Jika ada yang mendaftar dan membeli poin, Anda akan mendapatkan **Komisi 30%** dari nominal yang mereka beli!\n\n"
        f"🔗 **Link Undangan Anda:**\n`{ref_link}`\n\n"
        f"📊 **Statistik Affiliate Anda:**\n"
        f"👥 Total Teman: `{len(aff_data.get('friends', []))} orang`\n"
        f"💰 Total Komisi (Sepanjang Waktu): `{rupiah(aff_data.get('total_commission', 0))}`\n"
        f"💳 Saldo Tersedia: `{rupiah(aff_data.get('balance', 0))}`\n\n"
        f"📌 _Minimal penarikan Rp 5.000 dan Maksimal Rp 99.000.000_"
    )
    
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=user.id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass

    new_msg = await context.bot.send_message(
        chat_id=user.id, 
        text=text, 
        reply_markup=get_affiliate_keyboard(aff_data.get('balance', 0)), 
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    context.user_data['last_bot_msg_id'] = new_msg.message_id

async def handle_riwayat_wd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # PERUBAHAN DI SINI UNTUK MOTOR ASYNC
    history = await withdrawals_col.find({"user_id": user_id}).sort("created_at", -1).limit(5).to_list(length=None)
    
    if not history:
        text = "📜 **Riwayat Penarikan**\n\nBelum ada riwayat penarikan."
    else:
        text = "📜 **5 Riwayat Penarikan Terakhir**\n\n"
        for h in history:
            status_emoji = "⏳" if h['status'] == "pending" else "✅" if h['status'] == "success" else "❌"
            text += f"🔖 Kode: `{h['wd_id']}`\n💰 Nominal: {rupiah(h['amount'])}\n📌 Status: {status_emoji} {h['status'].upper()}\n📅 Tanggal: {h['created_at']}\n\n"
            
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali ke Affiliate", callback_data="menu_affiliate")]])
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=user_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass
    new_msg = await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
    context.user_data['last_bot_msg_id'] = new_msg.message_id



# ==========================================
# TAMBAHKAN DI BAGIAN PALING BAWAH FILE
# ==========================================
async def handle_tarik_locked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⚠️ Saldo komisi Anda belum mencapai minimal penarikan (Rp 5.000).", show_alert=True)
    return 0 # Kembali ke CHOOSING_FEATURE

async def handle_tarik_komisi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    aff_data = await affiliates_col.find_one({"user_id": user_id})
    if not aff_data or aff_data.get('balance', 0) < 5000:
        await query.answer("⚠️ Saldo tidak mencukupi.", show_alert=True)
        return 0
        
    text = (
        f"💸 **TARIK KOMISI**\n\n"
        f"Saldo Tersedia: `{rupiah(aff_data.get('balance', 0))}`\n\n"
        f"Silakan balas pesan ini dengan **Nominal** yang ingin ditarik (Hanya angka).\n"
        f"Contoh: `50000`\n\n"
        f"_Klik Batal untuk membatalkan penarikan._"
    )
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="cancel")]])
    
    if 'last_bot_msg_id' in context.user_data:
        try: await context.bot.delete_message(chat_id=user_id, message_id=context.user_data['last_bot_msg_id'])
        except Exception: pass

    new_msg = await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
    context.user_data['last_bot_msg_id'] = new_msg.message_id
    
    return 12 # Pindah ke state WAITING_WD_AMOUNT

async def handle_wd_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        # Mengantisipasi jika input kosong atau bukan text
        msg_text = update.message.text or ""
        amount = int(msg_text.replace(".", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("⚠️ Harap masukkan angka yang valid tanpa huruf. Contoh: 50000")
        return 12
    except Exception as e:
        await update.message.reply_text(f"⚠️ Gagal membaca angka: {str(e)}")
        return 12
        
    try:
        aff_data = await affiliates_col.find_one({"user_id": user_id})
        balance = aff_data.get('balance', 0) if aff_data else 0
        
        if amount < 5000:
            await update.message.reply_text("⚠️ Minimal penarikan adalah Rp 5.000. Silakan masukkan nominal yang benar:")
            return 12
            
        if amount > balance:
            await update.message.reply_text(f"⚠️ Saldo tidak mencukupi! Saldo Anda: {rupiah(balance)}. Silakan masukkan ulang:")
            return 12
            
        context.user_data['wd_amount'] = amount
        
        text = (
            f"🏦 **INFORMASI REKENING / E-WALLET**\n\n"
            f"Nominal Penarikan: `{rupiah(amount)}`\n\n"
            f"Silakan balas pesan ini dengan format:\n"
            f"`Nama Bank/E-Wallet - Nomor Rekening - Atas Nama`\n\n"
            f"Contoh: `DANA - 08123456789 - Budi Santoso`"
        )
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="cancel")]])
        new_msg = await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data['last_bot_msg_id'] = new_msg.message_id
        
        return 13 # Pindah ke state WAITING_WD_INFO
        
    except Exception as e:
        await update.message.reply_text(f"⚠️ Terjadi kesalahan sistem: {str(e)}")
        return 12

async def handle_wd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = update.message.text or ""
    amount = context.user_data.get('wd_amount', 0)
    
    try:
        if amount <= 0:
            await update.message.reply_text("⚠️ Terjadi kesalahan. Silakan ulangi proses penarikan dari awal.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data="main_menu")]]))
            return 0
            
        # Potong saldo user
        await affiliates_col.update_one({"user_id": user_id}, {"$inc": {"balance": -amount}})
        wd_id = f"WD-{uuid.uuid4().hex[:6].upper()}"
        
        # Simpan riwayat penarikan ke DB
        wd_data = {
            "wd_id": wd_id,
            "user_id": user_id,
            "amount": amount,
            "info": info,
            "status": "pending",
            "created_at": datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M:%S')
        }
        await withdrawals_col.insert_one(wd_data)
        
        # Kirim log notifikasi ke channel/admin
        log_channel = os.getenv("LOG_PEMBAYARANKOMISI")
        if log_channel:
            admin_text = (
                f"🚨 <b>REQUEST WITHDRAWAL BARU</b> 🚨\n\n"
                f"🧾 <b>ID WD:</b> <code>{wd_id}</code>\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"👤 <b>Username:</b> @{update.effective_user.username}\n"
                f"💰 <b>Nominal:</b> {rupiah(amount)}\n"
                f"🏦 <b>Info Tujuan:</b>\n<code>{info}</code>\n\n"
                f"<i>Gunakan /success {wd_id} untuk konfirmasi pembayaran selesai.</i>"
            )
            try: await context.bot.send_message(chat_id=log_channel, text=admin_text, parse_mode="HTML")
            except Exception as e: print(f"Gagal kirim log WD: {e}")
            
        success_text = (
            f"✅ **Pengajuan Penarikan Berhasil!**\n\n"
            f"🧾 ID Penarikan: `{wd_id}`\n"
            f"💰 Nominal: `{rupiah(amount)}`\n"
            f"🏦 Tujuan: `{info}`\n\n"
            f"⏳ _Mohon tunggu, penarikan Anda sedang ditinjau dan akan segera diproses oleh Admin._"
        )
        
        await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="main_menu")]]))
        
        context.user_data.clear()
        return 0 # Kembali ke CHOOSING_FEATURE
        
    except Exception as e:
        await update.message.reply_text(f"⚠️ Gagal memproses penarikan: {str(e)}")
        return 13