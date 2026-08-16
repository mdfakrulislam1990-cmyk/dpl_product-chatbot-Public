# -*- coding: utf-8 -*-
"""
প্রোডাক্ট চ্যাটবট — AI (Cohere) ভার্সন — ডাইনামিক উত্তর
===========================================================
এটা আগের fuzzy-matching বটের বদলে একটা আসল AI (LLM) ব্যবহার করে।
পদ্ধতি: RAG (Retrieval-Augmented Generation)
    ১. Excel থেকে সব প্রোডাক্টের তথ্য একটা টেক্সট আকারে বানানো হয়
    ২. কাস্টমার যা প্রশ্ন করে, সেটার সাথে এই পুরো প্রোডাক্ট তথ্য
       Cohere AI মডেলকে (command-a-03-2025) "context" হিসেবে দেওয়া হয়
    ৩. AI নিজেই বুঝে, প্রশ্নটা যেভাবেই করা হোক (ভুল বানান, আংশিক নাম,
       ঘুরিয়ে-পেঁচিয়ে প্রশ্ন), সঠিক প্রোডাক্ট খুঁজে বাংলায় স্বাভাবিক
       ভাষায় উত্তর দেয়।

চালানোর আগে করণীয়:
    ১. .env.example ফাইলটার নাম বদলে .env করুন
    ২. .env ফাইলে আপনার Cohere API key বসান
    ৩. pip install -r requirements.txt
    ৪. python app.py
"""

import os
import pandas as pd
import cohere
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()  # .env ফাইল থেকে API key লোড হবে

EXCEL_FILE = os.path.join(os.path.dirname(__file__), "products.xlsx")
COHERE_API_KEY = os.environ.get("CO_API_KEY")
COHERE_MODEL = "command-a-03-2025"

app = Flask(__name__)

if not COHERE_API_KEY:
    print("⚠️  CO_API_KEY পাওয়া যায়নি! .env ফাইলে আপনার Cohere API key বসান।")

co_client = cohere.ClientV2(api_key=COHERE_API_KEY) if COHERE_API_KEY else None


class ProductChatbot:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
        self.df = self.load_data()
        self.product_context = self.build_context()

    def load_data(self) -> pd.DataFrame:
        df = pd.read_excel(self.excel_path)
        df.columns = [c.strip() for c in df.columns]
        print(f"✅ {len(df)} টি প্রোডাক্ট লোড হয়েছে।")
        return df

    def build_context(self) -> str:
        """
        Excel এ যেই কলাম নামই থাকুক না কেন (Product Name/পণ্যের নাম/Item ইত্যাদি
        যেকোনো ভাষায় বা নামে), এই ফাংশন কলামের নাম হার্ডকোড না করে পুরো
        row-টাকেই 'কলাম-নাম: ভ্যালু' আকারে টেক্সট বানিয়ে দেয়। AI নিজেই
        বুঝে নেয় কোনটা দাম, কোনটা স্টক, কোনটা বিবরণ ইত্যাদি।
        """
        lines = []
        columns = self.df.columns.tolist()
        for idx, row in self.df.iterrows():
            parts = []
            for col in columns:
                value = row[col]
                if pd.isna(value):
                    value = "N/A"
                parts.append(f"{col}: {value}")
            lines.append(f"[Product {idx + 1}] " + " | ".join(parts))
        return "\n".join(lines)

    def refresh(self):
        """Excel ফাইল আবার নতুন করে পড়তে চাইলে (ডাটা আপডেট হলে) এটা কল করুন"""
        self.df = self.load_data()
        self.product_context = self.build_context()

    def build_system_prompt(self) -> str:
        return f"""তুমি একটা প্রোডাক্ট তথ্য সহায়ক চ্যাটবট। তোমার কাজ কাস্টমারের
প্রশ্নের উত্তর নিচে দেওয়া প্রোডাক্ট লিস্ট থেকে দেওয়া।

নিয়মাবলী:
1. কাস্টমার বাংলা, ইংরেজি, বাংলিশ (Banglish) — যেভাবেই প্রশ্ন করুক না কেন,
   তুমি বুঝে নিয়ে বাংলায় উত্তর দেবে। কাস্টমারের বানান ভুল হলে, প্রোডাক্টের
   নাম আংশিক বা ঘুরিয়ে লিখলেও, সবচেয়ে কাছাকাছি মিলে যাওয়া প্রোডাক্টটা
   বের করে উত্তর দেবে।
2. শুধুমাত্র নিচের প্রোডাক্ট লিস্টে যা আছে তা থেকেই উত্তর দেবে। লিস্টে
   নেই এমন কোনো তথ্য বানিয়ে বলবে না।
3. নিচের প্রোডাক্ট লিস্টে প্রতিটা প্রোডাক্টের তথ্য "কলামের নাম: ভ্যালু"
   ফরম্যাটে দেওয়া আছে। কলামের নামগুলো যেকোনো ভাষায় বা যেকোনো শব্দে হতে
   পারে (যেমন "Price" বা "দাম" বা "মূল্য" — সবই একই জিনিস বোঝাতে পারে)।
   তুমি নিজে বুদ্ধি খাটিয়ে বুঝে নেবে কোন কলামটা নাম, কোনটা দাম, কোনটা
   স্টক/পরিমাণ, কোনটা বিবরণ ইত্যাদি — তারপর সেই অনুযায়ী উত্তর দেবে।
4. কাস্টমার যদি শুধু দাম জানতে চায়, শুধু দাম বলবে। স্টক/পরিমাণ জানতে
   চাইলে শুধু সেটা বলবে। পুরো তথ্য চাইলে (বা বোঝা না গেলে) সব তথ্য
   সুন্দর করে গুছিয়ে দেবে (তবে internal ID বা row নম্বরের মতো
   অপ্রয়োজনীয় টেকনিক্যাল তথ্য দেখাবে না)।
5. প্রশ্নের সাথে মিলে এমন প্রোডাক্ট লিস্টে না থাকলে, ভদ্রভাবে বলবে যে
   পাওয়া যায়নি এবং লিস্টে থাকা কয়েকটা প্রোডাক্টের নাম উদাহরণ হিসেবে
   বলবে।
6. উত্তর সংক্ষিপ্ত, স্পষ্ট ও বন্ধুত্বপূর্ণ রাখবে। ইমোজি ব্যবহার করতে
   পারো (📦 💰 ✅ ❌)।
7. একাধিক প্রোডাক্ট প্রশ্নের সাথে মিলে গেলে (যেমন ক্যাটাগরি জিজ্ঞেস করলে),
   সবগুলো তালিকা আকারে দেখাবে।

প্রোডাক্ট লিস্ট:
{self.product_context}
"""

    def answer(self, query: str, history: list = None) -> str:
        if not query.strip():
            return "দয়া করে কিছু জিজ্ঞেস করুন।"

        if co_client is None:
            return "⚠️ সার্ভারে Cohere API key সেট করা নেই। .env ফাইল চেক করুন।"

        messages = [{"role": "system", "content": self.build_system_prompt()}]

        if history:
            for h in history[-6:]:
                messages.append(h)

        messages.append({"role": "user", "content": query})

        try:
            response = co_client.chat(
                model=COHERE_MODEL,
                messages=messages,
                temperature=0.3,
            )
            return response.message.content[0].text
        except Exception as e:
            print(f"❌ Cohere API এরর: {e}")
            return "😕 দুঃখিত, এই মুহূর্তে উত্তর দিতে সমস্যা হচ্ছে। একটু পরে আবার চেষ্টা করুন।"


bot = ProductChatbot(EXCEL_FILE)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_msg = data.get("message", "")
    history = data.get("history", [])
    reply = bot.answer(user_msg, history)
    return jsonify({"reply": reply})


@app.route("/refresh-data", methods=["POST"])
def refresh_data():
    bot.refresh()
    return jsonify({"status": "ok", "message": f"{len(bot.df)} টি প্রোডাক্ট রিলোড হয়েছে।"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
