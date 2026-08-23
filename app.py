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

    def load_data(self) -> dict:
        """
        এক্সেল ফাইলের সব শীট আলাদা আলাদা DataFrame হিসেবে লোড করা হয়।
        রিটার্ন হয় {শীটের নাম: DataFrame} — যেমন
        {"Medicine": df1, "Cosmetics": df2, "Grocery": df3, "Electronics": df4}
        নতুন শীট যোগ করলে বা বাদ দিলে কোড বদলানোর দরকার নেই, এটা
        স্বয়ংক্রিয়ভাবে সব শীট ধরে নেবে।
        """
        sheets = pd.read_excel(self.excel_path, sheet_name=None)
        total = 0
        for name, df in sheets.items():
            df.columns = [str(c).strip() for c in df.columns]
            sheets[name] = df
            total += len(df)
            print(f"✅ শীট '{name}' থেকে {len(df)} টি প্রোডাক্ট লোড হয়েছে।")
        print(f"✅ মোট {total} টি প্রোডাক্ট লোড হয়েছে ({len(sheets)} টি শীট থেকে)।")
        return sheets

    def build_context(self):
        """
        প্রতিটা প্রোডাক্ট/সারিকে একটা আলাদা টেক্সট লাইন হিসেবে বানিয়ে
        একটা লিস্টে রাখা হয় (পুরো একটা বড় স্ট্রিং না বানিয়ে)। এতে
        পরে Smart Retrieval এর সময় শুধু প্রয়োজনীয় লাইনগুলো বেছে নিয়ে
        AI কে পাঠানো যায় — পুরো ২০০+ প্রোডাক্ট প্রতিবার পাঠাতে হয় না।
        প্রতিটা এন্ট্রি: {"sheet": শীটের নাম, "text": প্রদর্শনযোগ্য টেক্সট,
        "search_text": লোয়ারকেস সার্চের জন্য}
        """
        entries = []
        product_no = 1
        for sheet_name, df in self.df.items():
            columns = df.columns.tolist()
            for _, row in df.iterrows():
                parts = [f"ক্যাটাগরি(শীট): {sheet_name}"]
                for col in columns:
                    value = row[col]
                    if pd.isna(value):
                        value = "N/A"
                    parts.append(f"{col}: {value}")
                text = f"[Product {product_no}] " + " | ".join(parts)
                entries.append({
                    "sheet": sheet_name,
                    "text": text,
                    "search_text": text.lower(),
                })
                product_no += 1
        return entries

    def refresh(self):
        """Excel ফাইল আবার নতুন করে পড়তে চাইলে (ডাটা আপডেট হলে) এটা কল করুন"""
        self.df = self.load_data()
        self.product_context = self.build_context()

    def get_relevant_entries(self, query: str, history: list = None, max_items: int = 25) -> list:
        """
        Smart Retrieval: প্রতিটা মেসেজে সব প্রোডাক্ট না পাঠিয়ে, প্রশ্নের
        (এবং সাম্প্রতিক কথোপকথনের) সাথে সবচেয়ে বেশি মিল থাকা প্রোডাক্টগুলো
        বেছে নেওয়া হয়। এতে Cohere-কে পাঠানো ডাটা অনেক ছোট থাকে —
        ফলে রেসপন্স দ্রুত আসে, মেমোরি কম লাগে, timeout/crash কমে যায়।

        পদ্ধতি: সহজ কিন্তু কার্যকর কীওয়ার্ড-ওভারল্যাপ স্কোরিং।
        (চাইলে পরে embedding-ভিত্তিক সার্চ দিয়ে আরও উন্নত করা যাবে,
        কিন্তু এখনকার স্কেলের জন্য এটাই যথেষ্ট এবং কোনো এক্সট্রা খরচ নেই।)
        """
        # প্রশ্ন + শেষ ২টা হিস্টরি মেসেজ মিলিয়ে সার্চ টেক্সট বানানো হয়,
        # যাতে "ওটার দাম কত?" এর মতো প্রশ্নেও আগের প্রসঙ্গ কাজে লাগে
        search_query = query
        if history:
            recent = history[-2:]
            search_query = " ".join(h.get("content", "") for h in recent) + " " + query
        search_query = search_query.lower()

        # ২ অক্ষরের বেশি লম্বা শব্দগুলোই কীওয়ার্ড হিসেবে ধরা হচ্ছে
        words = [w for w in search_query.replace("?", " ").replace(",", " ").split() if len(w) > 1]

        scored = []
        for entry in self.product_context:
            score = sum(1 for w in words if w in entry["search_text"])
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_entries = [e for _, e in scored[:max_items]]

        # FAQ শীট সবসময় ছোট, তাই কোনো কীওয়ার্ড না মিললেও FAQ গুলো
        # পাঠিয়ে দেওয়া হয় যাতে সাধারণ স্বাস্থ্য প্রশ্নের উত্তর দিতে পারে
        faq_entries = [e for e in self.product_context if e["sheet"].strip().upper() == "FAQ"]
        for fe in faq_entries:
            if fe not in top_entries:
                top_entries.append(fe)

        # কোনো কীওয়ার্ড ম্যাচ না পেলে (যেমন "কি কি প্রোডাক্ট আছে?" জাতীয়
        # প্রশ্ন), প্রথম কিছু প্রোডাক্ট ফলব্যাক হিসেবে দেখানো হয় যাতে
        # বট অন্তত কিছু উদাহরণ দিতে পারে এবং খালি হাতে না থাকে
        if not scored:
            fallback = self.product_context[:max_items]
            for fb in fallback:
                if fb not in top_entries:
                    top_entries.append(fb)

        return top_entries

    def build_system_prompt(self, context_text: str) -> str:
        return f"""তুমি Delta Care এর একটা প্রোডাক্ট ও স্বাস্থ্য তথ্য সহায়ক চ্যাটবট।
তোমার কাজ কাস্টমারের প্রশ্নের উত্তর নিচে দেওয়া তথ্য লিস্ট থেকে দেওয়া।
নিচের লিস্টে দুই ধরনের তথ্য থাকতে পারে: (ক) প্রোডাক্ট/ওষুধের তথ্য
(দাম, স্টক, জেনেরিক, ডোজ ইত্যাদি) এবং (খ) "FAQ" শীট থেকে সাধারণ
রোগ-ব্যাধি সংক্রান্ত প্রশ্নোত্তর। কাস্টমার যেই ধরনের প্রশ্নই করুক
(প্রোডাক্ট নিয়ে বা রোগ/লক্ষণ/চিকিৎসা নিয়ে), সংশ্লিষ্ট অংশ থেকে
উত্তর খুঁজে দেবে।

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
{context_text}
"""

    def answer(self, query: str, history: list = None) -> str:
        if not query.strip():
            return "দয়া করে কিছু জিজ্ঞেস করুন।"

        if co_client is None:
            return "⚠️ সার্ভারে Cohere API key সেট করা নেই। .env ফাইল চেক করুন।"

        # Smart Retrieval: সব প্রোডাক্টের বদলে শুধু প্রাসঙ্গিক প্রোডাক্টগুলো বাছাই
        relevant_entries = self.get_relevant_entries(query, history, max_items=25)
        context_text = "\n".join(e["text"] for e in relevant_entries)

        messages = [{"role": "system", "content": self.build_system_prompt(context_text)}]

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
    total = sum(len(df) for df in bot.df.values())
    return jsonify({
        "status": "ok",
        "message": f"{total} টি প্রোডাক্ট ({len(bot.df)} টি শীট থেকে) রিলোড হয়েছে।"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
