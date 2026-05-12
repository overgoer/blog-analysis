#!/usr/bin/env python3
"""ANALYST Agent — Channel Content Analyzer. Runs nightly."""
import json, datetime, os, re
from collections import Counter

CHANNEL_DATA = "/root/blog-analysis/data/eddytester_raw.json"
OUTPUT_DIR = "/root/blog-analysis/agents/analyst"

def load_channel():
    with open(CHANNEL_DATA) as f:
        data = json.load(f)
    if isinstance(data, dict):
        msgs = data.get("messages", data.get("posts", []))
    else:
        msgs = data if isinstance(data, list) else []
    return [m for m in msgs if isinstance(m, dict) and m.get("text")]

def get_text(p):
    text = p.get("text", "")
    if isinstance(text, list):
        return " ".join(str(t) for t in text if isinstance(t, str))
    return text or ""

def categorize_post(p):
    text = get_text(p)
    tl = text.lower()
    has_meme = any(w in tl for w in ["#memes", "#meme", "@memes", "мем"])
    has_file = bool(p.get("file"))
    
    if has_meme:
        return "meme"
    if any(w in tl for w in ["баг", "баги", "багом", "багов", "ошибк"]):
        return "bugs"
    if any(w in tl for w in ["гайд", "шпаргалк", "инструмент", "совет", "туториал"]):
        return "guide"
    if any(w in tl for w in ["собесед", "резюме", "ваканс", "карьер", "грейд", "найм"]):
        return "career"
    if any(w in tl for w in ["подкаст", "терка", "выпуск", "гость", "интервью"]):
        return "podcast"
    if any(w in tl for w in ["практикум", "practicum", "api", "postman", "endpoint"]):
        return "practicum"
    if any(w in tl for w in ["опрос", "вопрос", "что думае", "а у тебя", "как у вас", "делис"]):
        return "engagement"
    if any(w in tl for w in ["gpt", "ai ", "нейросет", "claude", "openai", "чатгпт", "llm"]):
        return "ai"
    if any(w in tl for w in ["новост", "вышл", "запустил", "релиз", "анонс"]):
        return "news"
    if any(w in tl for w in ["подкаст", "терка"]):
        return "podcast"
    if has_file and len(text) < 30:
        return "image"
    if len(text.split()) < 30:
        return "short"
    return "other"

def analyze_posts(posts):
    results = dict(
        total_posts=len(posts),
        by_category=Counter(),
        with_images=0,
        post_dates=[],
        recent_posts=[]
    )
    for p in posts:
        text = get_text(p)
        cat = categorize_post(p)
        results["by_category"][cat] += 1
        if p.get("file"):
            results["with_images"] += 1
        date_raw = p.get("date", "")
        if isinstance(date_raw, (int, float)):
            try:
                dt = datetime.datetime.fromtimestamp(date_raw)
                results["post_dates"].append(dt.isoformat()[:10])
            except:
                pass
    for p in posts[:20]:
        text = get_text(p)
        cats = categorize_post(p)
        date_raw = p.get("date", "")
        if isinstance(date_raw, (int, float)):
            try:
                date_str = datetime.datetime.fromtimestamp(date_raw).isoformat()[:10]
            except:
                date_str = str(date_raw)
        else:
            date_str = str(date_raw)
        results["recent_posts"].append(dict(date=date_str, category=cats, preview=text[:80]))
    return results

def generate_report(analysis):
    now = datetime.datetime.now()
    dt_str = now.strftime("%d %B %Y")
    lines = ["# ANALYST Report | " + dt_str, "",
             "## Overview",
             "- Total posts analyzed: " + str(analysis["total_posts"]),
             "- With images/media: " + str(analysis["with_images"]), "",
             "## Content Mix"]
    total = analysis["total_posts"] or 1
    for cat, count in analysis["by_category"].most_common():
        pct = count / total * 100
        lines.append("- " + cat + ": " + str(count) + " posts (" + f"{pct:.0f}%)")
    lines += ["",
              "## Recent Posts (last 20)"]
    for p in analysis["recent_posts"][:10]:
        lines.append("- [" + p["date"] + "] (" + p["category"] + ") " + p["preview"])
    lines += ["",
              "## Recommendations"]
    cats = analysis["by_category"]
    tc = analysis["total_posts"]
    if cats.get("practicum", 0) / tc * 100 < 5 and tc > 0:
        lines.append("- LOW practicum mentions - increase posts linking to the API and bot")
    if cats.get("engagement", 0) / tc * 100 < 3 and tc > 0:
        lines.append("- LOW engagement posts - add more polls, questions, quizzes")
    if cats.get("guide", 0) / tc * 100 < 5 and tc > 0:
        lines.append("- LOW guide content - readers want more how-to posts")
    if cats.get("bugs", 0) / tc * 100 < 5 and tc > 0:
        lines.append("- LOW bug content - this is your core niche, increase bug posts")
    if cats.get("career", 0) / tc * 100 > 15 and tc > 0:
        lines.append("- HIGH career content ratio - balance with more technical QA posts")
    lines.append("")
    return "\n".join(lines)

if __name__ == "__main__":
    posts = load_channel()
    analysis = analyze_posts(posts)
    report = generate_report(analysis)
    today = datetime.date.today().isoformat()
    out_path = os.path.join(OUTPUT_DIR, "report_" + today + ".md")
    with open(out_path, "w") as f:
        f.write(report)
    latest_path = os.path.join(OUTPUT_DIR, "latest_report.md")
    with open(latest_path, "w") as f:
        f.write(report)
    json_path = os.path.join(OUTPUT_DIR, "latest_analysis.json")
    with open(json_path, "w") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print("ANALYST report: " + out_path)
    print("Posts analyzed: " + str(analysis["total_posts"]))
