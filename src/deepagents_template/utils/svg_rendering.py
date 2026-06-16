"""Helpers for writing SVG review files and rendering them to PNG previews."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def wrap_svg_fragment(
    svg_fragment: str,
    *,
    view_box: tuple[int, int, int, int],
) -> str:
    x, y, width, height = view_box
    return (
        f'<svg xmlns="{SVG_NAMESPACE}" width="{width}" height="{height}" '
        f'viewBox="{x} {y} {width} {height}">\n'
        f"{svg_fragment.strip()}\n"
        "</svg>"
    )


def _candidate_node_executables() -> list[Path]:
    candidates: list[Path] = []
    from_path = shutil.which("node")
    if from_path:
        candidates.append(Path(from_path))
    home = Path.home()
    candidates.extend(
        [
            home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
            home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node",
        ]
    )
    return [path for path in candidates if path.is_file()]


def _candidate_node_module_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules",
    ]
    return [path for path in candidates if path.is_dir()]


def render_svg_file_to_png(svg_path: Path, png_path: Path) -> bool:
    node_executable = next(iter(_candidate_node_executables()), None)
    if node_executable is None:
        return False

    script = (
        "const fs = require('fs');"
        "const sharp = require('sharp');"
        "const [svgPath, pngPath] = process.argv.slice(1);"
        "sharp(fs.readFileSync(svgPath), { density: 144 }).png().toFile(pngPath)"
        ".catch((error) => { console.error(error?.stack || String(error)); process.exit(1); });"
    )
    env = os.environ.copy()
    module_roots = _candidate_node_module_roots()
    if module_roots:
        joined = os.pathsep.join(str(path) for path in module_roots)
        existing = env.get("NODE_PATH")
        env["NODE_PATH"] = f"{joined}{os.pathsep}{existing}" if existing else joined

    try:
        subprocess.run(
            [str(node_executable), "-e", script, str(svg_path), str(png_path)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return png_path.is_file()


def write_svg_review_artifacts(
    *,
    svg_text: str,
    svg_path: Path,
    png_path: Path,
) -> tuple[Path, Path | None]:
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_text, encoding="utf-8")
    png_rendered = render_svg_file_to_png(svg_path, png_path)
    return svg_path, png_path if png_rendered else None


def write_temp_svg_review_png(
    *,
    svg_text: str,
    suffix: str = ".svg",
    png_suffix: str = ".png",
) -> tuple[Path, Path | None]:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
        handle.write(svg_text)
        svg_path = Path(handle.name)
    png_path = svg_path.with_suffix(png_suffix)
    return svg_path, png_path if render_svg_file_to_png(svg_path, png_path) else None
