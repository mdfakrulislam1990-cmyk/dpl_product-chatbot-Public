# -*- coding: utf-8 -*-
"""
প্রোডাক্ট চ্যাটবট — ওয়েব ভার্সন (Flask)
==========================================
এটা আগের product_chatbot.py এর একই লজিক, শুধু এখন এটা একটা ওয়েবসাইট
হিসেবে চলে। ব্রাউজারে খুললেই একটা চ্যাটবক্স দেখা যাবে।

লোকালি চালানোর নিয়ম:
    python app.py
তারপর ব্রাউজারে যান: http://127.0.0.1:5000

ইন্টারনেটে লিংক পেতে (public URL) নিচের deployment guide দেখুন।
"""

import os
import pandas as pd
from fuzzywuzzy import fuzz
from flask import Flask, request, jsonify, render_template

EXCEL_FILE = os.path.join(os.path.dirname(__file__), "products.xlsx")

app = Flask(__name__)


class ProductChatbot:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
        self.df = self.load_data()

    def load_data(self) -> pd.DataFrame:
        df = pd.read_excel(self.excel_path)
        df.columns = [c.strip() for c in df.columns]
        print(f"✅ {len(df)} টি প্রোডাক্ট লোড হয়েছে।")
        return df

    def find_best_match(self, query: str, threshold: int = 55):
        query = query.lower()
        best_score = 0
        best_idx = None
        for idx, row in self.df.iterrows():
            name = str(row.get("Product Name", "")).lower()
            desc = str(row.get("Description", "")).lower()
            category = str(row.get("Category", "")).lower()

            score_name = fuzz.partial_ratio(query, name)
            score_desc = fuzz.partial_ratio(query, desc)
            score_cat = fuzz.partial_ratio(query, category)

            score = max(score_name, score_desc * 0.8, score_cat * 0.9)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_score >= threshold:
            return self.df.loc[best_idx], best_score
        return None, best_score

    def find_all_matches(self, keyword: str, limit: int = 8):
        keyword = keyword.lower()
        matches = []
        for _, row in self.df.iterrows():
            text = f"{row.get('Product Name','')} {row.get('Category','')} {row.get('Description','')}".lower()
            if keyword in text:
                matches.append(row)
        return matches[:limit]

    def format_product(self, row) -> str:
        name = row.get("Product Name", "N/A")
        price = row.get("Price", "N/A")
        stock = row.get("Stock", "N/A")
        category = row.get("Category", "N/A")
        desc = row.get("Description", "")

        try:
            stock_status = "✅ স্টকে আছে" if float(stock) > 0 else "❌ স্টক নেই"
        except (TypeError, ValueError):
            stock_status = "❓ অজানা"

        return (
            f"📦 <b>{name}</b><br>"
            f"• ক্যাটাগরি: {category}<br>"
            f"• মূল্য: {price} টাকা<br>"
            f"• স্টক: {stock} পিস ({stock_status})<br>"
            f"• বিবরণ: {desc}"
        )

    def detect_intent(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["দাম", "মূল্য", "price", "koto taka", "কত টাকা"]):
            return "price"
        if any(w in q for w in ["স্টক", "আছে কি", "stock", "available"]):
            return "stock"
        if any(w in q for w in ["লিস্ট", "সব প্রোডাক্ট", "list", "সব দেখাও", "ক্যাটাগরি"]):
            return "list"
        return "search"

    def answer(self, query: str) -> str:
        if not query.strip():
            return "দয়া করে কিছু জিজ্ঞেস করুন।"

        intent = self.detect_intent(query)

        if intent == "list":
            categories = self.df["Category"].dropna().unique().tolist()
            for cat in categories:
                if str(cat).lower() in query.lower():
                    matches = self.find_all_matches(cat)
                    if matches:
                        result = f"🔎 '{cat}' ক্যাটাগরিতে {len(matches)} টি প্রোডাক্ট পাওয়া গেছে:<br><br>"
                        result += "<br><br>".join(self.format_product(m) for m in matches)
                        return result
            result = f"🛍️ মোট {len(self.df)} টি প্রোডাক্ট আছে:<br><br>"
            result += "<br><br>".join(self.format_product(r) for _, r in self.df.iterrows())
            return result

        match, score = self.find_best_match(query)

        if match is None:
            examples = ", ".join(self.df["Product Name"].head(3).tolist())
            return (
                "😕 দুঃখিত, আপনার প্রশ্নের সাথে মিলে এমন কোনো প্রোডাক্ট খুঁজে পাইনি।<br>"
                "প্রোডাক্টের নাম বা ক্যাটাগরি উল্লেখ করে আবার চেষ্টা করুন।<br>"
                f"উদাহরণ: {examples}"
            )

        if intent == "price":
            return f"💰 {match['Product Name']} এর মূল্য: {match['Price']} টাকা।"

        if intent == "stock":
            stock = match["Stock"]
            try:
                status = "স্টকে আছে ✅" if float(stock) > 0 else "স্টকে নেই ❌"
            except (TypeError, ValueError):
                status = "❓ অজানা"
            return f"📦 {match['Product Name']} — {stock} পিস {status}।"

        return self.format_product(match)


bot = ProductChatbot(EXCEL_FILE)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_msg = data.get("message", "")
    reply = bot.answer(user_msg)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
