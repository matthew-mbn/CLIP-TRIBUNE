"""Сборка кадра: один ролик, два экрана и реклама с удалённым фоном.

Здесь нет запуска процессов или SQL. Функции строят аргументы FFmpeg,
а video.render выполняет команду с отменой и проверкой результата.
"""


def media_input(path, *, start=0, loop=False, image=False):
    args = ["-loop", "1", "-framerate", "30"] if image else (["-stream_loop", "-1"] if loop else [])
    if start:
        args += ["-ss", str(start)]
    return args + ["-protocol_whitelist", "file,pipe", "-i", str(path)]


def fit_filter(width, height, fit="crop"):
    if fit == "fit":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"


def build(options, metadata, width, height, duration):
    """Возвращаем дополнительные входы, граф фильтров и размер готового кадра."""
    inputs, graph = [], []
    audio_inputs = [0] if metadata.get("audio") else []
    next_input = 1
    split = options.get("layout") == "split"
    if options.get("layout") == "webcam":
        from .schemas import WebcamRegion

        region = WebcamRegion.model_validate(options.get("webcam_region")).model_dump()
        top_height = (height // 2) // 2 * 2
        # Два ответвления одного видеопотока имеют одинаковые кадры и время.
        # Координаты относительные: FFmpeg пересчитает их при смене размера потока.
        crop = (
            f"crop=w='max(2,trunc(iw*{region['width']}/2)*2)':"
            f"h='max(2,trunc(ih*{region['height']}/2)*2)':"
            f"x='min(iw-ow,trunc(iw*{region['x']}/2)*2)':"
            f"y='min(ih-oh,trunc(ih*{region['y']}/2)*2)'"
        )
        graph += [
            f"[0:v]trim=duration={duration},setpts=PTS-STARTPTS,fps=30,split[game][camera]",
            "[game]" + fit_filter(width, top_height, options.get("main_fit", "crop")) + "[top]",
            "[camera]"
            + crop
            + ","
            + fit_filter(width, height - top_height, options.get("webcam_fit", "crop"))
            + "[bottom]",
            "[top][bottom]vstack=inputs=2:shortest=1[base]",
        ]
    elif split:
        secondary = options["split_source"]
        inputs += media_input(
            secondary["path"],
            start=options.get("secondary_start", 0),
            loop=options.get("secondary_loop", True),
        )
        next_input += 1
        # Чётные высоты необходимы H.264 / yuv420p. Сумма точно равна высоте экспорта.
        top_height = (height // 2) // 2 * 2
        for index, part_height, label in [(0, top_height, "top"), (1, height - top_height, "bottom")]:
            graph.append(
                f"[{index}:v]trim=duration={duration},setpts=PTS-STARTPTS,fps=30,"
                + fit_filter(width, part_height, options.get("split_fit", "crop"))
                + f"[{label}]"
            )
        graph.append("[top][bottom]vstack=inputs=2:shortest=1[base]")
        sound = options.get("split_audio", "top")
        audio_inputs = []
        if sound in ("top", "mix") and metadata.get("audio"):
            audio_inputs.append(0)
        if sound in ("bottom", "mix") and secondary["metadata"].get("audio"):
            audio_inputs.append(1)
    else:
        framing = options.get("framing", "blur")
        if framing == "original":
            width, height = metadata["width"] // 2 * 2, metadata["height"] // 2 * 2
            graph.append(f"[0:v]setpts=PTS-STARTPTS,scale={width}:{height},setsar=1[base]")
        elif framing == "crop":
            graph.append("[0:v]setpts=PTS-STARTPTS," + fit_filter(width, height) + "[base]")
        else:
            graph += [
                "[0:v]setpts=PTS-STARTPTS,split[bg][fg]",
                "[bg]" + fit_filter(width, height) + ",boxblur=20:2[back]",
                f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[front]",
                "[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1[base]",
            ]
    current = "base"
    ad = options.get("ad_source")
    if ad:
        banner = ad["mode"] == "banner"
        start = 0 if banner else ad["start"]
        if start >= duration:
            raise ValueError("Вставка начинается после конца ролика")
        length = duration if banner else (ad["duration"] or ad["metadata"]["duration"])
        if not banner and ad["kind"] == "video":
            length = min(length, ad["metadata"]["duration"])
        length = min(length, duration - start)
        inputs += media_input(ad["path"], loop=banner, image=ad["kind"] == "image")
        margin = round(min(width, height) * ad["margin_percent"] / 100)
        ad_width = max(2, int(min(width - 2 * margin, width * ad["width_percent"] / 100)) // 2 * 2)
        ad_height = max(2, (height - 2 * margin) // 2 * 2)
        color = "0x" + ad["key_color"][1:]
        # Сначала убираем фон в RGB, затем уменьшаем изображение вместе с альфой.
        graph.append(
            f"[{next_input}:v]trim=duration={length},setpts=PTS-STARTPTS,format=rgba,"
            f"colorkey={color}:{ad['similarity']}:{ad['blend']},"
            f"scale={ad_width}:{ad_height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"setsar=1,setpts=PTS+{start}/TB[advert]"
        )
        position = ad["position"]
        x = str(margin) if "left" in position else (f"W-w-{margin}" if "right" in position else "(W-w)/2")
        y = str(margin) if "top" in position else (f"H-h-{margin}" if "bottom" in position else "(H-h)/2")
        graph.append(
            f"[base][advert]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0:"
            f"enable='gte(t,{start})*lt(t,{start + length})'[advertised]"
        )
        current = "advertised"
    # Для роликов без звука не создаём искусственную аудиодорожку.
    for index in audio_inputs:
        graph.append(
            f"[{index}:a:0]atrim=duration={duration},asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={duration}[sound{index}]"
        )
    if audio_inputs:
        labels = "".join(f"[sound{index}]" for index in audio_inputs)
        mix = f"amix=inputs={len(audio_inputs)}:duration=longest," if len(audio_inputs) > 1 else ""
        graph.append(labels + mix + f"atrim=duration={duration},loudnorm=I=-16:TP=-1.5:LRA=11[audio]")
    return inputs, graph, current, bool(audio_inputs), width, height
