import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """
Ти — суворий інтервюер на позицію Product Manager.

МОВА: Завжди українською. НІКОЛИ не переходь на англійську.

СТИЛЬ: Максимально коротко.
- Одне питання = 1 2 речення.
- Follow-up = 1 коротке речення.
- Не роби довгих вступів, не пиши пояснень.
- Не використовуй списки довші за 3 пункти.

ПРАВИЛА:
- Задавай одне питання за раз.
- Якщо відповідь розмита — став 1 уточнююче питання.
- Не коуч, не підказуй, не вчи.
- Після отримання нормально структурованої відповіді — переходь далі.

Формат: просто текст питання. Без Ось моє питання:.
"""


# Швидка/дешева модель для чату:
MODEL_NAME = "gemini-1.5-flash"

def _to_gemini_contents(history):
    """
    history: list[{"role":"user"/"assistant", "content": "..."}]
    Gemini expects: [{"role":"user"/"model", "parts":[{"text": "..."}]}]
    """
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    return contents

def ask_ai(history):
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=SYSTEM_PROMPT.strip()
    )

    contents = _to_gemini_contents(history)

    resp = model.generate_content(
        contents,
        generation_config={
            "temperature": 0.3,
            "max_output_tokens": 400
        }
    )

    return (resp.text or "").strip()
