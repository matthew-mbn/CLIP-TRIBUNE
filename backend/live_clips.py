"""Монтаж завершённых частей эфира: контекст на границе и защита от повторов."""

from pathlib import Path
from tempfile import TemporaryDirectory
import shutil

from sqlalchemy import select

from . import video
from .config import FFMPEG, STORAGE
from .models import LiveRecording, LiveSegment, RenderedClip, RenderJob, SourceAsset, uid
from .providers import HttpSpeechProvider, write_srt
from .security import file_hash, inside
from .source_identity import recording_identity
from .youtube import secret
from .database import settings


def concatenate(paths, output, cancelled):
    """Копируем сжатые дорожки, не перекодируя часы записи."""
    with TemporaryDirectory(dir=STORAGE / "temp") as temporary:
        listing = Path(temporary) / "parts.txt"
        lines = ["file '" + inside(path).as_posix().replace("'", "'\\''") + "'" for path in paths]
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        video.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c",
                "copy",
                str(output),
            ],
            cancelled,
            timeout=7200,
        )


def normalize_parts(parts, metadata, folder, recording, job, session, cancelled):
    """Рекламная пауза Twitch может изменить размер кадра внутри того же потока.

    Только для неодинаковых частей приводим видео и звук к единому формату.
    Обычная запись по-прежнему объединяется без перекодирования.
    """
    reference = metadata[0]
    factor = min(1, recording.options.get("height", 720) / reference["height"])
    width = max(2, round(reference["width"] * factor / 2) * 2)
    height = max(2, round(reference["height"] * factor / 2) * 2)
    threads = settings(session)["threads"]
    paths = []

    def checked():
        if cancelled():
            return True
        if shutil.disk_usage(STORAGE).free < 1024**3:
            raise ValueError("Недостаточно места для выравнивания формата. Исходные части сохранены")
        return False

    for index, (part, info) in enumerate(zip(parts, metadata)):
        job.message = f"Выравнивание формата записи: {index + 1}/{len(parts)}"
        job.progress = 5 + index / len(parts) * 80
        session.commit()
        output = Path(folder) / f"normalized_{index:06}.mkv"
        command = [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(inside(part.path)),
        ]
        if not info["audio"]:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        command += [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if info["audio"] else "1:a:0",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-af",
            "aresample=48000,asetpts=PTS-STARTPTS",
            "-t",
            str(part.duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            str(threads),
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-b:a",
            "128k",
            str(output),
        ]
        video.run(command, checked)
        paths.append(output)
    return paths


def process(session, job, options, cancelled):
    from .worker import save_clip

    part = session.get(LiveSegment, options["segment_id"])
    recording = session.get(LiveRecording, options["live_id"])
    if not part or not recording:
        raise ValueError("Часть эфира не найдена")
    previous = session.scalar(
        select(LiveSegment)
        .where(LiveSegment.recording_id == recording.id, LiveSegment.start < part.start)
        .order_by(LiveSegment.start.desc())
    )
    current_metadata = video.probe(inside(part.path))
    if previous:
        other_metadata = video.probe(inside(previous.path))
        if any(other_metadata[k] != current_metadata[k] for k in ("width", "height", "codec", "audio")):
            previous = None  # После смены формата не склеиваем несовместимые дорожки.
    with TemporaryDirectory(dir=STORAGE / "temp") as temporary:
        path = Path(part.path)
        origin = part.start
        start_min = 0
        if previous:
            path = Path(temporary) / "window.mkv"
            concatenate([previous.path, part.path], path, cancelled)
            origin = previous.start
            # Допускаем начало перед границей, чтобы реакция не теряла подводку.
            start_min = max(0, previous.duration - options["duration"])
        metadata = video.probe(path)
        if metadata["duration"] < options["duration"]:
            job.message = "Часть короче клипа; сохранена в полной записи"
            return
        used = []
        already = 0
        for clip in session.scalars(
            select(RenderedClip)
            .join(RenderJob, RenderJob.id == RenderedClip.job_id)
            .where(RenderJob.kind == "live_clip")
        ):
            data = clip.metadata_json
            if data.get("live_id") == recording.id:
                used.append(
                    dict(start=data["recording_start"] - origin, duration=clip.duration, fingerprint="")
                )
            if clip.job_id == job.id:
                already += 1
        remaining = options["count"] - already
        if remaining <= 0:
            job.message = "Нарезки этой части уже сохранены"
            return
        features = video.analyze(path, metadata, cancelled)
        candidates = video.select_candidates(
            features,
            metadata["duration"],
            options["duration"],
            remaining,
            used,
            options["min_score"],
            "Gaming Viral",
            start_min,
        )
        if not candidates:
            job.message = "Моментов выше порога нет; запись сохранена"
            return
        transcript, warning = [], ""
        if options.get("subtitles"):
            if secret("SPEECH_API_URL"):
                try:
                    transcript = HttpSpeechProvider().transcribe(str(path))
                except Exception:
                    warning = "Распознавание недоступно; экспорт без субтитров"
            else:
                warning = "SpeechProvider не настроен; экспорт без субтитров"
        for index, candidate in enumerate(candidates):
            if cancelled():
                raise video.Cancelled()
            job.status, job.progress = "rendering", 25 + index / len(candidates) * 70
            job.message = f"Момент эфира {index + 1}/{len(candidates)}"
            session.commit()
            output = STORAGE / "clips" / (uid() + ".mp4")
            subtitle_path = output.with_suffix(".srt")
            has_subtitles = write_srt(transcript, candidate["start"], candidate["duration"], subtitle_path)
            rendered = False
            try:
                video.render(
                    path,
                    output,
                    candidate,
                    options,
                    metadata,
                    cancelled,
                    subtitle_path if has_subtitles else None,
                )
                rendered = True
                save_clip(
                    session,
                    job,
                    None,
                    None,
                    output,
                    candidate,
                    options["theme"],
                    warning,
                    transcript,
                    source_name=recording.title,
                    metadata_extra=dict(
                        **recording_identity(recording),
                        live_id=recording.id,
                        recording_start=origin + candidate["start"],
                        segment_id=part.id,
                    ),
                )
            except Exception:
                if not rendered:
                    output.unlink(missing_ok=True)
                    subtitle_path.unlink(missing_ok=True)
                raise
        job.message = f"Сохранено моментов эфира: {len(candidates) + already}"


def export(session, job, cancelled):
    recording = session.get(LiveRecording, job.options["live_id"])
    if not recording or recording.active_slot is not None:
        raise ValueError("Запись ещё идёт или не найдена")
    parts = session.scalars(
        select(LiveSegment).where(LiveSegment.recording_id == recording.id).order_by(LiveSegment.start)
    ).all()
    if not parts:
        raise ValueError("Нет частей записи")
    if shutil.disk_usage(STORAGE).free < sum(p.size for p in parts) + 1024**3:
        raise ValueError("Недостаточно места для сборки записи; исходные части сохранены")
    metadata = [video.probe(part.path) for part in parts]
    changed = any(
        any(info[k] != metadata[0][k] for k in ("width", "height", "codec", "audio")) for info in metadata[1:]
    )
    destination = STORAGE / "sources" / (uid() + ".mkv")
    try:
        with TemporaryDirectory(dir=STORAGE / "temp") as temporary:
            paths = (
                normalize_parts(parts, metadata, temporary, recording, job, session, cancelled)
                if changed
                else [p.path for p in parts]
            )
            if shutil.disk_usage(STORAGE).free < sum(Path(p).stat().st_size for p in paths) + 1024**3:
                raise ValueError("Недостаточно места для итоговой записи; исходные части сохранены")
            concatenate(paths, destination, cancelled)
        digest = file_hash(destination)
        asset = session.scalar(select(SourceAsset).where(SourceAsset.sha256 == digest))
        if asset:
            destination.unlink(missing_ok=True)
        else:
            asset = SourceAsset(
                name=recording.title + " · эфир.mkv",
                path=str(destination),
                sha256=digest,
                rights=True,
                metadata_json={**video.probe(destination), **recording_identity(recording)},
            )
            session.add(asset)
        session.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    job.message = "Полная запись готова в разделе «Источники»"
    job.options = {**job.options, "export_asset_id": asset.id}
