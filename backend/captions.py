"""Редактируемые фразы и ASS-оформление. Время всегда относительно готового клипа."""

import shutil
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from .config import FFMPEG
from . import video

STYLES = {
    "classic": ("Arial", 46, 0, "&H00FFFFFF", 1, 2),
    "bold": ("Arial", 58, -1, "&H00FFFFFF", 1, 4),
    "box": ("Arial", 48, -1, "&H00FFFFFF", 3, 8),
    "red": ("Arial", 58, -1, "&H004040FF", 1, 4),
}


class Cue(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(max_length=500)
    enabled: bool = True

    @model_validator(mode="after")
    def valid_time(self):
        if self.end <= self.start:
            raise ValueError("Конец фразы должен быть позже начала")
        return self


class CaptionEdit(BaseModel):
    style: Literal["classic", "bold", "box", "red"] = "bold"
    cues: list[Cue] = Field(default_factory=list, max_length=3000)


def ass_time(value):
    cs = round(value * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def write_ass(path, edit):
    font, size, bold, color, border, outline = STYLES[edit.style]
    text = "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 0\n\n[V4+ Styles]\n"
    text += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    text += f"Style: Default,{font},{size},{color},&H00FFFFFF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,{border},{outline},0,2,45,45,180,1\n\n[Events]\n"
    text += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    for cue in sorted(edit.cues, key=lambda c: c.start):
        if not cue.enabled or not cue.text.strip():
            continue
        # Фигурные скобки и обратные слеши не должны становиться командами ASS.
        safe = (
            cue.text.replace("\\", "／")
            .replace("{", "(")
            .replace("}", ")")
            .replace("\r", "")
            .replace("\n", r"\N")
        )
        text += f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},Default,,0,0,0,,{safe}\n"
    Path(path).write_text(text, encoding="utf-8-sig")


def prepare(output, transcript, start, duration, options):
    from .composition import ad_timing

    ad_start, length, pause = ad_timing(options, duration)
    cues = []
    for row in transcript:
        a, b = max(0, row["start"] - start), min(duration, row["end"] - start)
        if b <= a:
            continue
        spans = [(a, b)]
        if pause:
            spans = []
            if a < ad_start:
                spans.append((a, min(b, ad_start)))
            if b > ad_start:
                spans.append((max(a, ad_start) + length, b + length))
        cues.extend(dict(start=x, end=y, text=row["text"]) for x, y in spans if y > x)
    edit = CaptionEdit(style=options.get("subtitle_style", "bold"), cues=cues)
    Path(output).with_suffix(".captions.json").write_text(edit.model_dump_json(), encoding="utf-8")
    if not cues:
        return None
    path = Path(output).with_suffix(".ass")
    write_ass(path, edit)
    return path


def load(clip):
    path = Path(clip.path).with_suffix(".captions.json")
    return (
        CaptionEdit.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else CaptionEdit()
    )


def clean_source(clip):
    # Новые версии сохраняют чистый мастер. На старых вшитые буквы удалить нельзя.
    path = Path(clip.path).with_suffix(".clean.mp4")
    return path if path.exists() else Path(clip.path)


def burn(source, output, ass, options, cancelled=lambda: False):
    escaped = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    video.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"subtitles=filename='{escaped}'",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            str(options.get("threads", 2)),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
        cancelled,
    )
    return video.probe(output)


def process(session, job, options, cancelled):
    from .models import RenderedClip, uid
    from .worker import save_clip
    from .config import STORAGE
    from . import speech

    if job.kind == "speech_setup":
        job.message = "Загрузка модели распознавания: 148 МБ"
        session.commit()
        speech.install(cancelled)
        job.message = "Модель готова; распознавание работает локально"
        return
    clip = session.get(RenderedClip, options["clip_id"])
    if not clip:
        raise ValueError("Ролик не найден")
    source = clean_source(clip)
    if job.kind == "caption_transcribe":
        rows = speech.transcribe(source, cancelled)
        prepare(clip.path, rows, 0, clip.duration, options)
        job.message = "Субтитры распознаны. Откройте редактор из библиотеки"
        return
    edit = CaptionEdit.model_validate(options["captions"])
    output = STORAGE / "clips" / (uid() + ".mp4")
    master = output.with_suffix(".clean.mp4")
    shutil.copyfile(source, master)
    ass = output.with_suffix(".ass")
    write_ass(ass, edit)
    try:
        burn(master, output, ass, options, cancelled)
        output.with_suffix(".captions.json").write_text(edit.model_dump_json(), encoding="utf-8")
        save_clip(
            session,
            job,
            None,
            None,
            output,
            dict(start=0, duration=clip.duration, score=clip.score, reasons=["Редактирование субтитров"]),
            "",
            source_clip=clip,
            title_suffix=" · субтитры",
            metadata_extra={"live_id": None, "render_options": clip.metadata_json.get("render_options", {})},
        )
    except Exception:
        for path in (output, master, ass, output.with_suffix(".captions.json")):
            path.unlink(missing_ok=True)
        raise
    job.message = "Копия с субтитрами готова в библиотеке"
