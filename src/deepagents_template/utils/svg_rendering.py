"""Helpers for writing SVG review files and rendering them to PNG previews."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from deepagents_template.atomic_files import atomic_write_text

SVG_NAMESPACE = "http://www.w3.org/2000/svg"


@dataclass(frozen=True)
class SvgRenderResult:
    """Result from rendering an SVG preview image."""

    ok: bool
    png_path: Path | None
    renderer: str | None = None
    error: str | None = None
    stderr: str | None = None


class SvgPreviewRenderError(RuntimeError):
    """Raised when an SVG preview image cannot be rendered."""

    def __init__(self, *, scope: str, svg_path: Path, png_path: Path, error_path: Path, render_result: SvgRenderResult) -> None:
        renderer = render_result.renderer or "unknown renderer"
        detail = render_result.error or render_result.stderr or "unknown render error"
        super().__init__(
            f"SVG preview render failed for {scope}: {detail} "
            f"(renderer={renderer}; error_log={error_path})"
        )
        self.scope = scope
        self.svg_path = svg_path
        self.png_path = png_path
        self.error_path = error_path
        self.render_result = render_result


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
    home = Path.home()
    candidates.extend(
        [
            home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
            home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node",
        ]
    )
    from_path = shutil.which("node")
    if from_path:
        candidates.append(Path(from_path))
    return [path for path in candidates if path.is_file()]


def _candidate_node_module_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    candidates: list[Path] = [
        home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules",
    ]
    for path in candidates:
        if not path.is_dir():
            continue
        roots.append(path)
        pnpm_root = path / ".pnpm"
        if pnpm_root.is_dir():
            roots.extend(
                candidate
                for candidate in (item / "node_modules" for item in pnpm_root.iterdir())
                if candidate.is_dir()
            )
    return roots


def render_svg_file_to_png_detailed(svg_path: Path, png_path: Path) -> SvgRenderResult:
    node_executable = next(iter(_candidate_node_executables()), None)
    if node_executable is None:
        return SvgRenderResult(
            ok=False,
            png_path=None,
            error="No Node.js executable found for SVG preview rendering.",
        )

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
    except OSError as exc:
        return SvgRenderResult(
            ok=False,
            png_path=None,
            renderer=f"sharp:{node_executable}",
            error=str(exc),
        )
    except subprocess.CalledProcessError as exc:
        return SvgRenderResult(
            ok=False,
            png_path=None,
            renderer=f"sharp:{node_executable}",
            error=str(exc),
            stderr=(exc.stderr or "").strip() or None,
        )
    if not png_path.is_file():
        return SvgRenderResult(
            ok=False,
            png_path=None,
            renderer=f"sharp:{node_executable}",
            error="SVG renderer completed without producing a PNG file.",
        )
    return SvgRenderResult(ok=True, png_path=png_path, renderer=f"sharp:{node_executable}")


def render_svg_file_to_png(svg_path: Path, png_path: Path) -> bool:
    return render_svg_file_to_png_detailed(svg_path, png_path).ok


def write_svg_review_artifacts(
    *,
    svg_text: str,
    svg_path: Path,
    png_path: Path,
) -> tuple[Path, Path | None, SvgRenderResult]:
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(svg_path, svg_text)
    render_result = render_svg_file_to_png_detailed(svg_path, png_path)
    return svg_path, render_result.png_path if render_result.ok else None, render_result


def write_temp_svg_review_png(
    *,
    svg_text: str,
    suffix: str = ".svg",
    png_suffix: str = ".png",
) -> tuple[Path, Path | None, SvgRenderResult]:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
        handle.write(svg_text)
        svg_path = Path(handle.name)
    png_path = svg_path.with_suffix(png_suffix)
    render_result = render_svg_file_to_png_detailed(svg_path, png_path)
    return svg_path, render_result.png_path if render_result.ok else None, render_result
