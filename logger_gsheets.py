# -*- coding: utf-8 -*-
"""
logger_gsheets.py
------------------
কাস্টমারের প্রশ্ন ও bot-এর উত্তর সরাসরি Google Sheet এ সেভ করে।
Render restart/redeploy হলেও ডাটা হারায় না (লোকাল ফাইলের মতো ephemeral না)।

এই ফাইলটা app.py এর ঠিক পাশে (একই ফোল্ডারে) রাখতে হবে।

দরকারি Environment Variable (Render এ আগে থেকেই সেট করা আছে ধরে নিচ্ছি):
    GOOGLE_CREDS_JSON  -> Service Account এর পুরো JSON key (এক স্ট্রিং হিসেবে)

Google Sheet এর নাম হতে হবে ঠিক: "Delta Care Chat Logs"
(এবং Service Account email কে Editor হিসেবে শেয়ার করা থাকতে হবে)
"""

import os
import json
import threading
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

_lock = threading.Lock()
SHEET_NAME = "Delta Care Chat Logs"

_worksheet = None  # lazy-loaded, একবার connect হলে পরে reuse করা হয়


def _get_worksheet():
    """Google Sheet এর সাথে কানেকশন তৈরি করে (প্রথমবার), পরে cache থেকে রিটার্ন করে।"""
    global _worksheet
    if _worksheet is not None:
        return _worksheet

    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDS_JSON environment variable সেট করা নেই।")

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open(SHEET_NAME)
    ws = sheet.sheet1

    # শীট একদম খালি হলে হেডার বসিয়ে দেওয়া
    if not ws.get_all_values():
        ws.append_row(["Timestamp", "User Question", "Bot Answer", "User IP"])

    _worksheet = ws
    return _worksheet


def _write_row(question: str, answer: str, user_ip: str):
    """আসল লেখার কাজ — এটা background thread এ চলবে।"""
    try:
        with _lock:
            ws = _get_worksheet()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws.append_row([timestamp, question, answer, user_ip])
    except Exception as e:
        # লগিং ফেইল করলেও যেন মূল চ্যাটবট চলতে থাকে, তাই এখানে শুধু print করা হচ্ছে
        print(f"⚠️ Google Sheets এ লগ সেভ করা যায়নি: {e}")


def log_chat_async(question: str, answer: str, user_ip: str = ""):
    """
    Non-blocking log: কাস্টমারকে অপেক্ষা করতে হবে না।
    /chat route থেকে এই ফাংশনটা কল করলেই হবে।
    """
    t = threading.Thread(target=_write_row, args=(question, answer, user_ip), daemon=True)
    t.start()
