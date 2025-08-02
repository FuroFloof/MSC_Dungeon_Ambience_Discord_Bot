import discord
from discord.ext import commands
from discord import app_commands
import asyncio  # needed for run_in_executor
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageSequence
import os
import tempfile
import numpy as np

# ─────────────────────────────────────────────────────
# OPTIONAL VIDEO SUPPORT (moviepy)
# ─────────────────────────────────────────────────────
try:
    from moviepy import VideoFileClip, ImageClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# ─────────────────────────────────────────────────────
# CONFIGURATION CONSTANTS
# ─────────────────────────────────────────────────────
TOKEN = " "  # supply your token or use env var
FONT_PATH = "./fonts/font.ttf"  # TrueType font for captions
PADDING = 12                    # px top / bottom padding inside caption bar
MIN_FONT_SIZE = 12             # stops binary‑search shrinking
CHUNK_WORDS = 5                # forced line break after N words
TARGET_LONG_SIDE = 720         # every media’s longest dimension after scaling

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────────────
# TEXT / FONT HELPERS
# ─────────────────────────────────────────────────────

def _get_font(size: int) -> ImageFont.ImageFont:
    """Return a FreeType font at *size* (fallback to default)."""
    if os.path.isfile(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size)
    return ImageFont.load_default()

def _chunk_lines(text: str, chunk_size: int = CHUNK_WORDS):
    """Hard‑wrap caption after *chunk_size* words."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        for i in range(0, len(words), chunk_size):
            lines.append(" ".join(words[i : i + chunk_size]))
    return lines

def _best_fit(draw: ImageDraw.ImageDraw, text: str, width: int):
    """Find largest font size so every wrapped line fits within *width*."""
    lo, hi = MIN_FONT_SIZE, width
    best_font, best_lines = _get_font(MIN_FONT_SIZE), _chunk_lines(text)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _get_font(mid)
        lines = _chunk_lines(text)
        if all(draw.textlength(l, font=font) <= width - 2 * PADDING for l in lines):
            best_font, best_lines = font, lines
            lo = mid + 2  # try larger
        else:
            hi = mid - 2  # too big
    return best_lines, best_font

# ─────────────────────────────────────────────────────
# SCALING HELPERS – *always* hit TARGET_LONG_SIDE
# ─────────────────────────────────────────────────────

def _resize_keep_aspect(img: Image.Image, max_side: int):
    """Scale *img* so its longest edge == *max_side* (up or down)."""
    w, h = img.size
    scale = max_side / max(w, h)
    if scale == 1:
        return img.copy()
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.LANCZOS)

# ─────────────────────────────────────────────────────
# CAPTION BAR CREATOR
# ─────────────────────────────────────────────────────

def _make_caption_bar(width: int, caption: str):
    dummy = Image.new("RGB", (width, 10))
    d = ImageDraw.Draw(dummy)
    lines, font = _best_fit(d, caption, width)
    lh = font.getbbox("A")[3] - font.getbbox("A")[1]
    bar_h = lh * len(lines) + 2 * PADDING
    bar = Image.new("RGBA", (width, bar_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(bar)
    y = PADDING
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((width - tw) // 2, y), line, fill=(0, 0, 0), font=font)
        y += lh
    return bar

# ─────────────────────────────────────────────────────
# IMAGE & GIF PROCESSOR
# ─────────────────────────────────────────────────────

def _caption_image_or_gif(data: bytes, caption: str, filename: str):
    """Handle static images and GIFs, guaranteeing a valid 256‑colour palette."""

    img = Image.open(BytesIO(data))
    output = BytesIO()

    # ── STATIC IMAGE ────────────────────────────────────────────────
    if not getattr(img, "is_animated", False):
        fr = _resize_keep_aspect(img.convert("RGBA"), TARGET_LONG_SIDE)
        cap_bar = _make_caption_bar(fr.width, caption)
        canvas = Image.new("RGBA", (fr.width, fr.height + cap_bar.height), (255, 255, 255, 255))
        canvas.paste(cap_bar, (0, 0), cap_bar)
        canvas.paste(fr, (0, cap_bar.height), fr)

        ext = filename.split(".")[-1].lower()
        fmt = "PNG" if ext not in {"png", "jpg", "jpeg"} else ext.upper()
        canvas.save(output, format=fmt)
        output.seek(0)
        return output, f"captioned.{ext}"

        # ── ANIMATED GIF ───────────────────────────────────────────────
    frames_q, durations = [], []
    seq = ImageSequence.Iterator(img)

    # process first frame separately to build the master palette
    first_src = next(seq)
    first_resized = _resize_keep_aspect(first_src.convert("RGBA"), TARGET_LONG_SIDE)
    cap_bar = _make_caption_bar(first_resized.width, caption)
    cap_h = cap_bar.height
    first_canvas = Image.new("RGBA", (first_resized.width, first_resized.height + cap_h), (255, 255, 255, 255))
    first_canvas.paste(cap_bar, (0, 0), cap_bar)
    first_canvas.paste(first_resized, (0, cap_h), first_resized)

    master = first_canvas.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
    frames_q.append(master)
    durations.append(first_src.info.get("duration", 40))

    # subsequent frames reuse master palette
    for frame in seq:
        fr = _resize_keep_aspect(frame.convert("RGBA"), TARGET_LONG_SIDE)
        canvas = Image.new("RGBA", (fr.width, fr.height + cap_h), (255, 255, 255, 255))
        canvas.paste(cap_bar, (0, 0), cap_bar)
        canvas.paste(fr, (0, cap_h), fr)
        q = canvas.convert("RGB").quantize(palette=master)
        frames_q.append(q)
        durations.append(frame.info.get("duration", 40))

    frames_q[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames_q[1:],
        loop=img.info.get("loop", 0),
        duration=durations,
        disposal=2,
    )
    output.seek(0)
    return output, "captioned.gif"

# ─────────────────────────────────────────────────────
# VIDEO PROCESSOR (if MoviePy present)
# ─────────────────────────────────────────────────────
if MOVIEPY_AVAILABLE:
    def _caption_video(path: str, caption: str):
        clip = VideoFileClip(path)
        scale = TARGET_LONG_SIDE / max(clip.w, clip.h)
        clip_r = clip.resize(scale)
        bar_img = _make_caption_bar(int(clip_r.w), caption)
        bar_clip = ImageClip(np.array(bar_img)).set_duration(clip_r.duration)
        final = concatenate_videoclips([bar_clip, clip_r], method="compose").set_audio(clip_r.audio)
        temp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        final.write_videofile(temp_out.name, codec="libx264", audio_codec="aac", fps=clip_r.fps, verbose=False, logger=None)
        clip.close(); final.close()
        return temp_out
else:
    def _caption_video(*args, **kwargs):  # type: ignore
        raise RuntimeError("MoviePy not installed – install for video support.")

# ─────────────────────────────────────────────────────
# UNIVERSAL MEDIA ROUTER
# ─────────────────────────────────────────────────────

def _process_media(data: bytes, caption: str, filename: str):
    ext = filename.split(".")[-1].lower()
    if ext in {"png", "jpg", "jpeg", "gif"}:
        return _caption_image_or_gif(data, caption, filename)
    if ext in {"mp4", "mov", "mkv", "webm"}:
        if not MOVIEPY_AVAILABLE:
            raise RuntimeError("Video captioning requires MoviePy (pip install moviepy)")
        tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
        tmp_in.write(data); tmp_in.close()
        tmp_out = _caption_video(tmp_in.name, caption)
        with open(tmp_out.name, "rb") as f:
            vid_bytes = f.read()
        os.unlink(tmp_in.name); os.unlink(tmp_out.name)
        return BytesIO(vid_bytes), "captioned.mp4"
    raise ValueError(f"Unsupported file type: {ext}")

# ─────────────────────────────────────────────────────
# SLASH COMMAND
# ─────────────────────────────────────────────────────

@bot.tree.command(name="caption", description="Add a caption to any media (image, GIF, video)")
@app_commands.describe(text="Caption text", attachment="Attach media", url="Direct media URL")
async def caption(interaction: discord.Interaction, text: str, attachment: discord.Attachment | None = None, url: str | None = None):
    """Slash command entrypoint. Heavy processing is moved to a background thread so the bot stays responsive and Discord gets its ACK on time."""

    # respond immediately so Discord doesn't time‑out the interaction
    await interaction.response.defer(thinking=True)

    data: bytes | None = None
    filename = "media"

    try:
        if attachment:
            data = await attachment.read(); filename = attachment.filename
        elif url:
            r = requests.get(url, timeout=15); r.raise_for_status()
            data = r.content; filename = url.split("/")[-1] or "download"
        else:
            await interaction.followup.send("Attach a file or provide a URL.")
            return

        # heavy CPU work (Pillow quantising, resizing, etc.) → run in thread
        loop = asyncio.get_running_loop()
        output, out_name = await loop.run_in_executor(None, _process_media, data, text, filename)

    except Exception as exc:
        await interaction.followup.send(f"Error: {exc}")
        return

    await interaction.followup.send(file=discord.File(fp=output, filename=out_name))
    await interaction.response.defer()
    data: bytes | None = None
    filename = "media"
    try:
        if attachment:
            data = await attachment.read(); filename = attachment.filename
        elif url:
            r = requests.get(url, timeout=15); r.raise_for_status()
            data = r.content; filename = url.split("/")[-1] or "download"
        else:
            await interaction.followup.send("Attach a file or provide a URL."); return
        output, out_name = _process_media(data, text, filename)
    except Exception as exc:
        await interaction.followup.send(f"Error: {exc}"); return
    await interaction.followup.send(file=discord.File(fp=output, filename=out_name))

# ─────────────────────────────────────────────────────
# BOT LIFECYCLE
# ─────────────────────────────────────────────────────

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Caption bot logged in as {bot.user}")

bot.run(TOKEN)
