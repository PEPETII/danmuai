"""证明 API 调用真实性的对照测试：有知识 vs 无知识"""
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.retriever import KnowledgeRetriever

API_KEY = "sk-5b8ece87b2e2444385541c086b1773e5"
API_URL = "https://api.deepseek.com/v1/chat/completions"

# ---- 构造两组完全一样的输入，唯一差别是知识注入 ----
system_base = "你是一个直播弹幕互动游戏的 AI 助手。根据当前截图和上一轮弹幕，生成有趣、有梗的弹幕回复。回复格式为 JSON：{\"danmakus\": [{\"text\": \"弹幕内容\"}], \"scene_brief\": \"场景简述\", \"keywords\": [\"关键词\"]}"

user_pt = """当前画面：用户正在直播《艾尔登法环》，角色在关卡前方，旁边有一个 NPC。
上一轮弹幕：
  - 老头环好玩吗
  - 前期用什么职业好
  - 怎么加点啊
  - 这个 NPC 是谁"""

# A: 带知识注入
apd = os.environ["APPDATA"]
kb_path = Path(apd) / "DanmuAI" / "knowledge.db"
db = KnowledgeDatabase._open_at(kb_path)
retriever = KnowledgeRetriever(db)
result = retriever.retrieve(
    scene_brief="老头环新手问前期职业和加点",
    keywords=["艾尔登法环", "职业", "前期", "新手", "老头环", "加点"],
)
system_with_kb = f"{system_base}\n\n{result.prompt_text}" if result.prompt_text else system_base
db.close()

# B: 无知识注入（只保留基础 system prompt）
system_without_kb = system_base

def call_api(system_pt, label):
    print(f"\n{'='*60}")
    print(f"📤 [{label}] 正在发送...")
    print(f"{'='*60}")
    print(f"System prompt 最后 200 字: ...{system_pt[-200:]}")
    resp = httpx.post(
        API_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "system", "content": system_pt}, {"role": "user", "content": user_pt}],
            "temperature": 0.8,
            "max_tokens": 512,
        },
        timeout=30,
    )
    print(f"HTTP {resp.status_code}")
    if resp.status_code == 200:
        raw_content = resp.json()["choices"][0]["message"]["content"]
        print("\n📄 AI 原始回复:")
        print(repr(raw_content[:300]))
        print(f"... (共 {len(raw_content)} 字符)")
        # 智能解析：尝试取 JSON 块
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            # 可能包含 markdown 代码块包裹
            import re

            m = re.search(r"```(?:json)?\s*((?:.|\n)*?)```", raw_content)
            if m:
                parsed = json.loads(m.group(1).strip())
            else:
                print("\n⚠️ 非标准 JSON 格式，直接显示原始内容:")
                print(raw_content[:500])
                return None
        if "danmakus" not in parsed:
            parsed = {"danmakus": [{"text": d} if isinstance(d, str) else d for d in parsed.get("danmakus", [parsed.get("text", raw_content)[:200]])]}
        print("\n弹幕输出:")
        for d in parsed.get("danmakus", []):
            print(f"  💬 {d['text']}")
        return parsed
    else:
        print(f"错误: {resp.text[:300]}")
        return None

# 先调用有知识的
r1 = call_api(system_with_kb, "A - 带知识包注入")
# 再调用无知识的
r2 = call_api(system_without_kb, "B - 无知识包（对照组）")

if r1 and r2:
    print(f"\n{'='*60}")
    print("🔍 两组结果对比（唯一变量：是否有知识注入）")
    print(f"{'='*60}")
    for i, d1 in enumerate(r1.get("danmakus", [])):
        d2_text = r2["danmakus"][i]["text"] if i < len(r2["danmakus"]) else "(N/A)"
        print(f"\n 弹幕{i+1}:")
        print(f"   A(有知识): {d1['text']}")
        print(f"   B(无知识): {d2_text}")
