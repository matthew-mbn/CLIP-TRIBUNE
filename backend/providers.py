"""Необязательные AI-провайдеры. Без ключа работает честный шаблонный генератор."""

import json
from typing import Protocol

import httpx


class SpeechProvider(Protocol):
    def transcribe(self, path: str) -> list[dict]: ...


class VideoAnalysisProvider(Protocol):
    def describe(self, path: str, start: float, duration: float) -> dict: ...


class HttpSpeechProvider:
    def transcribe(self, path):
        from .youtube import secret

        with open(path, "rb") as stream:
            response = httpx.post(
                secret("SPEECH_API_URL"),
                headers={"Authorization": "Bearer " + secret("SPEECH_API_KEY")},
                files={"file": stream},
                timeout=600,
            )
        response.raise_for_status()
        segments = response.json()["segments"]
        for segment in segments:
            if not 0 <= float(segment["start"]) < float(segment["end"]):
                raise ValueError("Провайдер вернул неверные интервалы субтитров")
        return segments


def srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def write_srt(segments, start, duration, path):
    selected = []
    for segment in segments:
        begin = max(0, float(segment["start"]) - start)
        end = min(duration, float(segment["end"]) - start)
        if end > begin:
            selected.append(
                f"{len(selected) + 1}\n{srt_time(begin)} --> {srt_time(end)}\n{segment['text']}\n"
            )
    path.write_text("\n".join(selected), encoding="utf-8")
    return bool(selected)


def content_metadata(theme, source_name, candidate, transcript=""):
    from .youtube import secret

    subject = theme.strip() or source_name.rsplit(".", 1)[0]
    titles = [
        f"{subject} — фрагмент {int(candidate['start'])} сек.",
        f"{subject}: короткий эпизод",
        f"Момент из {subject}",
    ]
    result = dict(
        titles=[t[:100] for t in titles],
        description=f"Фрагмент исходника «{source_name}». Начало: {candidate['start']:.0f} сек.\n#Shorts",
        hashtags=["Shorts"],
        thumbnail_idea="Кадр из середины эпизода с коротким заголовком",
        category="22",
        provider="template",
        warning="Шаблонные метаданные: проверьте перед публикацией",
    )
    if not secret("AI_API_URL") or not secret("AI_MODEL"):
        return result
    try:
        response = httpx.post(
            secret("AI_API_URL"),
            timeout=45,
            headers={"Authorization": "Bearer " + secret("AI_API_KEY")},
            json={
                "model": secret("AI_MODEL"),
                "messages": [
                    {
                        "role": "system",
                        "content": "Return JSON with titles (3 strings), description, hashtags (list), thumbnail_idea. Use Russian. Do not invent events; use only supplied evidence. No markdown.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            dict(theme=theme, transcript=transcript, evidence=candidate["reasons"]),
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
        )
        response.raise_for_status()
        generated = json.loads(response.json()["choices"][0]["message"]["content"])
        if len(generated["titles"]) != 3 or not all(isinstance(t, str) for t in generated["titles"]):
            raise ValueError("Ожидались 3 заголовка")
        result.update({k: generated[k] for k in ("description", "hashtags", "thumbnail_idea")})
        result.update(
            titles=[t[:100] for t in generated["titles"]],
            provider="llm",
            warning="AI-метаданные требуют просмотра и проверки фактов",
        )
    except Exception:
        result["warning"] = "AI-провайдер недоступен; использованы шаблоны"
    return result
