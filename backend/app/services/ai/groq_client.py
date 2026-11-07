"""
Клиент Groq API для оценки диалогов с поддержкой модели qwen/qwen3.8-27b,
адаптивным бюджетом ответа, дифференциацией ошибок (429 минутный/дневной, 401, 5xx)
и полным учётом метрик токенов и задержек.
"""

import os
import json
import re
import time
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения строго из текущей папки проекта
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
env_path = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=env_path)

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")


class GroqClientError(Exception):
    """Базовое исключение клиента Groq."""
    def __init__(self, message: str, error_type: str = "GENERIC_ERROR"):
        super().__init__(message)
        self.error_type = error_type


class DailyQuotaExceededError(GroqClientError):
    """Дневной лимит запросов исчерпан."""
    def __init__(self, message: str):
        super().__init__(message, error_type="DAILY_LIMIT_EXCEEDED")


class AuthenticationError(GroqClientError):
    """Ошибка авторизации / недействительный API-ключ."""
    def __init__(self, message: str):
        super().__init__(message, error_type="AUTH_ERROR")


def clean_json_text(text: str) -> str:
    """Очищает ответ модели от тегов <think> и markdown блоков ```json ... ```"""
    text = text.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def evaluate_dialog_via_groq(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    api_key: str = None,
    max_completion_tokens: int = 800,
    max_retries: int = 5,
    max_total_wait_sec: float = 90.0
) -> Tuple[Dict[str, Any], float, Dict[str, Any]]:
    """
    Отправляет запрос в Groq API.

    Возвращает:
      - data: распарсенный JSON-ответ модели
      - model_call_time: чистое время ожидания вызова API (в секундах)
      - meta: словарь метаданных (total_time, retries, rate_limit_429_count, token_usage, model)
    """
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key or key.strip() in ["", "your_groq_api_key_here"]:
        raise AuthenticationError(
            "GROQ_API_KEY не задан! Укажите действительный ключ в файле .env или переменных окружения."
        )

    model_name = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)

    try:
        from groq import Groq, RateLimitError, AuthenticationError as GroqAuthError, APIStatusError
    except ImportError:
        raise ImportError("Пакет groq не установлен. Выполните: pip install groq")

    client = Groq(api_key=key)

    total_start_time = time.time()
    pure_model_time = 0.0
    response_text = ""
    attempt = 0
    rate_limit_429_count = 0
    total_waited_sec = 0.0
    current_tokens = max_completion_tokens
    token_usage = None

    while attempt <= max_retries:
        attempt += 1
        t_call_start = time.time()
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model=model_name,
                temperature=0.1,
                max_completion_tokens=current_tokens,
                response_format={"type": "json_object"}
            )
            pure_model_time += (time.time() - t_call_start)
            response_text = chat_completion.choices[0].message.content

            # Извлекаем точный расход токенов
            if hasattr(chat_completion, "usage") and chat_completion.usage is not None:
                token_usage = {
                    "prompt_tokens": chat_completion.usage.prompt_tokens,
                    "completion_tokens": chat_completion.usage.completion_tokens,
                    "total_tokens": chat_completion.usage.total_tokens
                }
            break

        except GroqAuthError as ae:
            raise AuthenticationError(f"Ошибка авторизации Groq (проверьте API ключ): {ae}")

        except RateLimitError as rle:
            pure_model_time += (time.time() - t_call_start)
            rate_limit_429_count += 1
            err_msg = str(rle)

            # Проверка: исчерпан ли ДНЕВНОЙ лимит (RPD)
            if "requests per day" in err_msg.lower() or "rpd" in err_msg.lower() or "daily" in err_msg.lower():
                raise DailyQuotaExceededError(
                    f"Дневная квота Groq исчерпана: {err_msg}. Повторы остановлены."
                )

            if attempt > max_retries or total_waited_sec >= max_total_wait_sec:
                raise GroqClientError(
                    f"Превышено максимальное число попыток ({max_retries}) или лимит ожидания ({max_total_wait_sec}с). Ошибка: {err_msg}",
                    error_type="RATE_LIMIT_EXHAUSTED"
                )

            # 1. Заголовок Retry-After
            wait_seconds = 8.0
            if hasattr(rle, "response") and rle.response is not None:
                header_val = (
                    rle.response.headers.get("retry-after")
                    or rle.response.headers.get("Retry-After")
                )
                if header_val:
                    try:
                        wait_seconds = float(header_val)
                    except ValueError:
                        pass

            # 2. Поиск "try again in X.XXs"
            match = re.search(r"try again in\s*([0-9.]+)\s*(s|ms)?", err_msg, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                unit = (match.group(2) or "s").lower()
                wait_seconds = val / 1000.0 if unit == "ms" else val

            # 3. Превышение размера запроса (Requested > Limit)
            if "reduce max_tokens" in err_msg or "expected output tokens exceed" in err_msg:
                if current_tokens > 450:
                    current_tokens = 450
                    print(f"  [Адаптация бюджета]: снижен max_completion_tokens до {current_tokens}", flush=True)
                elif current_tokens > 300:
                    current_tokens = 300
                    print(f"  [Адаптация бюджета]: снижен max_completion_tokens до {current_tokens}", flush=True)

            wait_seconds = max(wait_seconds + 1.0, 2.0)
            wait_seconds = min(wait_seconds, 60.0)

            # Проверяем общий лимит ожидания
            if total_waited_sec + wait_seconds > max_total_wait_sec:
                wait_seconds = max(max_total_wait_sec - total_waited_sec, 1.0)

            print(
                f"  [429 Groq RateLimit]: ожидание {wait_seconds:.1f}с по Retry-After "
                f"(попытка {attempt}/{max_retries}, 429_count={rate_limit_429_count}, max_tokens={current_tokens})...",
                flush=True
            )
            time.sleep(wait_seconds)
            total_waited_sec += wait_seconds

        except APIStatusError as ase:
            pure_model_time += (time.time() - t_call_start)
            # Временные ошибки сервера (5xx)
            if 500 <= ase.status_code < 600 and attempt <= max_retries:
                backoff = min(2.0 ** attempt, 30.0)
                print(f"  [5xx Ошибка сервера Groq ({ase.status_code})]: повтор через {backoff:.1f}с...", flush=True)
                time.sleep(backoff)
                total_waited_sec += backoff
            else:
                raise GroqClientError(f"Ошибка API Groq (HTTP {ase.status_code}): {ase}", error_type="API_STATUS_ERROR")

        except Exception as e:
            pure_model_time += (time.time() - t_call_start)
            raise GroqClientError(f"Сетевая или непредвиденная ошибка: {e}", error_type="NETWORK_ERROR")

    if not response_text:
        raise GroqClientError("Модель вернула пустой ответ после всех попыток.", error_type="EMPTY_RESPONSE")

    total_duration = time.time() - total_start_time

    cleaned = clean_json_text(response_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as jde:
        raise GroqClientError(
            f"Модель вернула некорректный или обрезанный JSON ({jde}). Сырой ответ: {response_text[:300]}",
            error_type="INVALID_JSON"
        )

    meta = {
        "model": model_name,
        "pure_model_time": round(pure_model_time, 2),
        "total_duration": round(total_duration, 2),
        "total_attempts": attempt,
        "rate_limit_429_count": rate_limit_429_count,
        "token_usage": token_usage
    }

    return data, pure_model_time, meta
