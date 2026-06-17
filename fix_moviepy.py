"""
fix_moviepy.py — Patches MoviePy 1.0.3 to work with Pillow 10+.
PIL.Image.ANTIALIAS was removed in Pillow 10; this replaces it with LANCZOS.
Run once: py fix_moviepy.py
"""
import inspect
import pathlib
import moviepy.video.fx.resize as resize_module

fix_file = pathlib.Path(inspect.getfile(resize_module))
original = fix_file.read_text(encoding="utf-8")

if "ANTIALIAS" not in original:
    print("Already patched — nothing to do.")
else:
    patched = original.replace("Image.ANTIALIAS", "Image.LANCZOS")
    fix_file.write_text(patched, encoding="utf-8")
    print(f"Patched: {fix_file}")
    print("MoviePy is now compatible with Pillow 10+. Run py pipeline.py again.")
