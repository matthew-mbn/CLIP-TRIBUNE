"""Расширяемые контракты и настоящий пример процедурной анимации.

Это геометрические персонажи, а не обещание готовой text-to-video модели.
"""

from pathlib import Path
from typing import Protocol

from .config import FFMPEG
from .video import run


class ScriptGenerator(Protocol):
    def generate(self, idea: str) -> list[dict]: ...


class StoryboardGenerator(Protocol):
    def storyboard(self, script: list[dict]) -> list[dict]: ...


class CharacterProvider(Protocol):
    def create(self, description: str) -> str: ...


class SceneRenderer(Protocol):
    def render(self, scene: dict, output: Path) -> Path: ...


class VoiceProvider(Protocol):
    def synthesize(self, text: str, output: Path) -> Path: ...


class VideoComposer(Protocol):
    def compose(self, scenes: list[Path], output: Path) -> Path: ...


def geometric_animation(output, cancelled=lambda: False):
    # overlay вычисляет координаты для каждого кадра: два персонажа встречаются.
    graph = (
        "[0:v][1:v]overlay=x='100+120*sin(t)':y='700+40*sin(t*3)'[a];"
        "[a][2:v]overlay=x='450-120*sin(t)':y='700-40*sin(t*3)',"
        "drawtext=text='CLIP TRIBUNE':fontcolor=white:fontsize=40:x=(w-tw)/2:y=200[v]"
    )
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x101014:s=720x1280:r=30:d=15",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xef3340:s=100x160:r=30:d=15",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=100x160:r=30:d=15",
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-t",
            "15",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        cancelled,
    )
