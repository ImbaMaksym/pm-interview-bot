import os
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# --- Python 3.9 hotfix for google-genai dependency expectations ---
import importlib.metadata as _im
try:
    _ = _im.packages_distributions
except AttributeError:
    try:
        import importlib_metadata as _imb  # backport
        _im.packages_distributions = _imb.packages_distributions
    except Exception:
        pass

from google import genai

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- report.py (твій файл) ---
from report import make_pdf_report

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

# ===== Settings =====
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
MAX_QUESTIONS = 10  # <-- тут ліміт питань

# Gemini client
gemini = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """Ти суворий інтерв'юер Product Manager.
Мова: українська.
Правила:
- 1 питання за раз.
- Питання коротке (1–2 речення).
- Якщо відповідь розмита — коротке уточнення (1 речення).
- Не підказуй і не навчай.
- Будь реалістичний і строгий.
"""

EVAL_PROMPT = """Ти інтерв'юер Product Manager. Мова: українська. Пиши коротко.
Зроби оцінку кандидата за інтерв'ю.

Формат:
Рівень: <junior/middle/senior>
Загальна оцінка: X/10
Рішення: PASS / MAYBE / NO

Скоринг по компетенціях:
- Product Sense: X/10
- Analytics: X/10
- Communication: X/10

Сильні сторони:
- ...
- ...
- ...

Зони росту:
- ...
- ...
- ...

План на 2 тижні:
- ...
- ...
- ...
- ...
- ...
"""

def load_db() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}

def save_db(db: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user_bucket(db: dict, user_id: str) -> dict:
    users = db.setdefault("users", {})
    return users.setdefault(user_id, {"attempts": []})

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def ask_ai_short(history):
    """
    history: list of {"role":"user"/"assistant","content":"..."}
    returns: next interviewer message (string)
    """
    parts = [SYSTEM_PROMPT.strip(), "\n\nДіалог:"]
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "assistant":
            parts.append(f"Інтерв'юер: {content}")
        else:
            parts.append(f"Кандидат: {content}")
    parts.append("\nІнтерв'юер:")

    prompt = "\n".join(parts)

    try:
        resp = gemini.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        return text if text else "Ок. Уточни, будь ласка, 1 метрику і 1 наступний крок."
    except Exception as e:
        return f"Помилка AI: {type(e).__name__}. Перевір ключ/квоту Gemini."

def ask_eval(level: str, history: list) -> str:
    dialog_lines = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant":
            dialog_lines.append(f"Інтерв'юер: {content}")
        else:
            dialog_lines.append(f"Кандидат: {content}")
    dialog = "\n".join(dialog_lines)

    prompt = (
        EVAL_PROMPT.strip()
        + "\n\n"
        + f"Рівень кандидата: {level}\n\n"
        + "Ось діалог:\n"
        + dialog
    )

    try:
        resp = gemini.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return (resp.text or "").strip() or "Не вдалося згенерувати оцінку."
    except Exception as e:
        return f"Помилка оцінки: {type(e).__name__}"

class Interview(StatesGroup):
    start = State()
    level = State()
    interview = State()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ===== Commands =====

@dp.message(F.text == "/start")
async def start(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Interview.start)
    await msg.answer(
        "Привіт.\nЯ проведу mock-інтервʼю на Product Manager.\n"
        f"Питань: до {MAX_QUESTIONS}.\n\n"
        "Напиши OK, щоб почати.\n"
        "Команди: /finish /retry /history"
    )

@dp.message(F.text.casefold() == "ok")
async def choose_level(msg: Message, state: FSMContext):
    await state.set_state(Interview.level)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Junior", callback_data="level_junior")],
        [InlineKeyboardButton(text="Middle", callback_data="level_middle")],
        [InlineKeyboardButton(text="Senior", callback_data="level_senior")],
    ])
    await msg.answer("Обери рівень:", reply_markup=kb)

@dp.message(F.text == "/retry")
async def retry(msg: Message, state: FSMContext):
    # просто заново вибір рівня (нова спроба)
    await state.clear()
    await msg.answer("Ок, нова спроба. Напиши OK і обери рівень.")
    await state.set_state(Interview.start)

@dp.message(F.text == "/history")
async def history(msg: Message, state: FSMContext):
    db = load_db()
    uid = str(msg.from_user.id)
    bucket = get_user_bucket(db, uid)
    attempts = bucket.get("attempts", [])

    if not attempts:
        await msg.answer("Історія пуста. Пройди інтервʼю і зроби /finish.")
        return

    # покажемо останні 5
    last = attempts[-5:][::-1]
    lines = []
    kb_rows = []
    for a in last:
        aid = a["id"]
        level = a.get("level", "?")
        score = a.get("score", "?")
        decision = a.get("decision", "?")
        ts = a.get("ts", "")[:10]
        lines.append(f"#{aid} — {ts} — {level} — {score}/10 — {decision}")
        kb_rows.append([InlineKeyboardButton(text=f"Відкрити #{aid}", callback_data=f"hist_{aid}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await msg.answer("Останні спроби:\n" + "\n".join(lines), reply_markup=kb)

@dp.callback_query(F.data.startswith("hist_"))
async def open_history(cb: CallbackQuery, state: FSMContext):
    aid = cb.data.replace("hist_", "").strip()
    db = load_db()
    uid = str(cb.from_user.id)
    bucket = get_user_bucket(db, uid)
    attempts = bucket.get("attempts", [])

    target = None
    for a in attempts:
        if str(a.get("id")) == aid:
            target = a
            break

    if not target:
        await cb.message.answer("Не знайшов цю спробу.")
        await cb.answer()
        return

    eval_text = target.get("evaluation_text", "")
    lines = [l.strip() for l in eval_text.split("\n") if l.strip()]
    title = "PM Mock Interview — Звіт"
    pdf_path = f"pm_report_{uid}_{aid}.pdf"

    try:
        make_pdf_report(pdf_path, title, lines)
        await cb.message.answer_document(FSInputFile(pdf_path), caption=f"Звіт #{aid} ✅")
    except Exception as e:
        await cb.message.answer(f"Не зміг зібрати PDF: {e}\n\nОсь текст:\n{eval_text[:3500]}")

    await cb.answer()

# ===== Interview flow =====

@dp.callback_query(F.data.startswith("level_"))
async def level_chosen(cb: CallbackQuery, state: FSMContext):
    level = cb.data.replace("level_", "").strip()

    await state.set_state(Interview.interview)

    history = [
        {"role": "user", "content": f"Рівень кандидата: {level}"},
        {"role": "user", "content": "Починай інтервʼю. Перше питання — product sense."}
    ]

    # q_count — лічильник питань інтерв'юера
    data = {
        "level": level,
        "history": history,
        "q_count": 0,
    }
    await state.update_data(**data)

    question = ask_ai_short(history)
    history.append({"role": "assistant", "content": question})
    await state.update_data(history=history, q_count=1)

    await cb.message.answer(question)
    await cb.answer()

@dp.message(Interview.interview)
async def interview(msg: Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    level = data.get("level", "junior")
    q_count = int(data.get("q_count", 0))

    text = (msg.text or "").strip()

    # /finish — формує оцінку + PDF + зберігає спробу
    if text.lower() == "/finish":
        await msg.answer("Ок, формую оцінку і PDF-звіт…")

        evaluation_text = ask_eval(level, history)

        # збережемо спробу в data.json
        db = load_db()
        uid = str(msg.from_user.id)
        bucket = get_user_bucket(db, uid)

        attempt_id = (bucket["attempts"][-1]["id"] + 1) if bucket["attempts"] else 1

        # спробуємо витягнути score/decision (простий парсинг)
        score = "?"
        decision = "?"
        for line in evaluation_text.splitlines():
            l = line.strip()
            if l.lower().startswith("загальна оцінка:"):
                # "Загальна оцінка: 4/10"
                score = l.split(":", 1)[-1].strip().split("/")[0]
            if l.lower().startswith("рішення:"):
                decision = l.split(":", 1)[-1].strip()

        bucket["attempts"].append({
            "id": attempt_id,
            "ts": now_iso(),
            "level": level,
            "questions": q_count,
            "score": score,
            "decision": decision,
            "evaluation_text": evaluation_text,
            "history": history,  # зберігаємо весь діалог
        })
        save_db(db)

        # PDF
        try:
            lines = [l.strip() for l in evaluation_text.split("\n") if l.strip()]
            pdf_path = f"pm_report_{uid}_{attempt_id}.pdf"
            make_pdf_report(pdf_path, "PM Mock Interview — Звіт", lines)
            await msg.answer_document(FSInputFile(pdf_path), caption=f"Ось твій PDF-звіт ✅ (спроба #{attempt_id})")
        except Exception as e:
            await msg.answer(f"Оцінку згенерував, але PDF не створився: {e}\n\n{evaluation_text[:3500]}")

        await state.clear()
        return

    # якщо вже досягли ліміту — просимо /finish
    if q_count >= MAX_QUESTIONS:
        await msg.answer(f"Ліміт {MAX_QUESTIONS} питань. Напиши /finish щоб отримати звіт ✅")
        return

    # додати відповідь користувача
    history.append({"role": "user", "content": text})

    # наступне питання
    next_msg = ask_ai_short(history)
    history.append({"role": "assistant", "content": next_msg})

    q_count += 1

    await state.update_data(history=history, q_count=q_count)
    await msg.answer(next_msg)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
