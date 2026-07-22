"""Agent personas: predefined categories → detailed system prompts, plus an
LLM-powered "suggest a system prompt" helper for the "Other" category.

The categories live in config.yaml (`categories:`) so they're editable without a
code change. `build_system_prompt` assembles the *effective* prompt from the
active agent config + the RAG/guardrail rules shared by every persona.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG, category_by_id  # noqa: E402
from agent.llm import complete  # noqa: E402

# Rules appended to every persona so behaviour is consistent (grounding + refusal).
GUARDRAILS = """
### لغة الكلام (مهم جداً)
- اتكلم **عامية مصرية صافية** زي ما المصريين بيتكلموا — **ممنوع الفصحى تماماً**،
  عشان الكلام يتقري صح بالصوت.
- استخدم الكلمات المصرية: «بيك/بيكي» مش «بك»، «إزاي» مش «كيف»، «عايز» مش «أريد»،
  «دلوقتي» مش «الآن»، «النهاردة» مش «اليوم»، «فين» مش «أين»، «ليه» مش «لماذا»،
  «كام» مش «كم»، «مفيش» مش «لا يوجد»، «أقدر أساعدك إزاي» مش «كيف يمكنني مساعدتك»،
  «آسف» مش «أنا آسف، لا أستطيع»، «تحب» مش «هل ترغب».
- أمثلة على الأسلوب الصح:
  • «وعليكم السلام ورحمة الله، أهلاً بيك في مطعم أبو السيد. أقدر أساعدك إزاي النهاردة؟»
  • «الكشري الكبير بـ 45 جنيه يا فندم.»
  • «معلش، دي حاجة مش موجودة عندي — أقدر أساعدك في حاجة تخص المطعم؟»

### الأرقام (مهم للنطق الصحيح)
- اكتب **كل** الأرقام بالأرقام الإنجليزية (0-9) مش الأرقام العربية — يعني 7 مش ٧،
  و 45 مش ٤٥، و 180 مش ١٨٠. ده ضروري عشان الصوت (TTS) ينطقها صح.

### قواعد أساسية (مهمة جداً)
- في الأسئلة المعلوماتية: اعتمد **فقط** على المعلومات اللي بتيجي من قاعدة المعرفة.
- لو المستخدم سأل عن حاجة اتقالت في المحادثة قبل كده (زي اسمه)، جاوب من سياق المحادثة.
- لو مفيش معلومة مناسبة، أو السؤال خارج نطاق تخصصك، اعتذر بأدب بالعامية ووضّح إنك
  تقدر تساعد فقط في الأسئلة المتعلقة بمجالك — **ولا تخمّن أو تخترع إجابة**.
- منع تام لاختلاق أرقام أو أسعار أو مواعيد مش موجودة في قاعدة المعرفة.
- في التحيات والشكر والكلام العادي: ردّ من شخصيتك بجملة قصيرة ودودة، **من غير**
  ما تذكر مصادر أو قاعدة معرفة.
- ردودك قصيرة ومباشرة (جملة أو جملتين).
- لما تعتمد على معلومة من قاعدة المعرفة، اذكر مصدرها باختصار في نهاية الرد.
"""


def categories() -> list[dict]:
    return [dict(c) for c in CFG.categories]


def prompt_for_category(cid: str) -> str:
    c = category_by_id(cid)
    return (c or {}).get("prompt", "").strip()


def build_system_prompt(agent_cfg=None) -> str:
    """Effective system prompt = agent persona + shared guardrails."""
    a = agent_cfg or CFG.agent
    base = (a.get("system_prompt") or "").strip() if isinstance(a, dict) \
        else (getattr(a, "system_prompt", "") or "").strip()
    name = a.get("name") if isinstance(a, dict) else getattr(a, "name", "")
    header = f"اسمك هو «{name}»." if name else ""
    return "\n".join(x for x in [header, base, GUARDRAILS] if x).strip()


def suggest_prompt(description: str, name: str = "") -> str:
    """Use the LLM to generate a detailed Arabic system prompt from a short
    free-text description of the agent's purpose (the 'Other' category flow)."""
    ask = f"""أنت خبير في كتابة الـ system prompts لمساعدين ذكيين صوتيين/نصيين.
اكتب system prompt تفصيلي بالعربية لمساعد ذكي بالمواصفات دي:
- اسم المساعد: {name or "غير محدد"}
- الغرض / المجال: {description}

المطلوب في الـ prompt:
1. تعريف واضح لشخصية المساعد ودوره ونبرة كلامه.
2. إنه يعتمد فقط على قاعدة المعرفة (المستندات المرفوعة) عند الإجابة.
3. إنه يرفض بأدب الأسئلة خارج نطاق تخصصه ولا يخمّن.
4. أسلوب مختصر وودود بالعربية.

اكتب الـ prompt النهائي فقط بدون أي مقدمات أو علامات تنسيق."""
    return complete(ask, temperature=0.6)
