"""Generate the application's simple vector-style music-note icon."""
from pathlib import Path
from PIL import Image, ImageDraw

size = 256
image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((6, 6, 250, 250), radius=56, fill="#087ca7")
draw.rounded_rectangle((117, 61, 134, 176), radius=8, fill="white")
draw.rounded_rectangle((179, 48, 196, 158), radius=8, fill="white")
draw.polygon([(124, 58), (189, 44), (189, 79), (124, 94)], fill="white")
draw.ellipse((77, 153, 134, 195), fill="white")
draw.ellipse((140, 136, 197, 178), fill="white")
image.save(Path(__file__).with_name("icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
