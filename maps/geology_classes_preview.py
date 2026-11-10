"""Renders geology_classes_preview.png: a swatch sheet of the shared
geology color table (geology_classes.json), for checking the palette as a
whole before using a new class on a map. Run from inside ../maps."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle

from geology_sgmc import load_classes

FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")

classes = load_classes()
fig, ax = plt.subplots(figsize=(8, 0.5 * len(classes) + 0.8), dpi=150)
fig.patch.set_facecolor("#f7f6f2")
ax.set_xlim(0, 10)
ax.set_ylim(len(classes), -1)
ax.axis("off")
ax.text(0, -0.6, "Shared geology color table", fontproperties=f_bold, fontsize=13)
for i, c in enumerate(classes):
    indent = 0.4 if c.get("parent") else 0
    ax.add_patch(Rectangle((indent, i + 0.1), 0.9, 0.7, facecolor=c["color"],
                           edgecolor=c.get("edge", "#8a877d"), linewidth=0.6))
    ax.text(indent + 1.1, i + (0.35 if c.get("age") else 0.5), c["label"],
            va="center", fontproperties=f_reg, fontsize=9)
    if c.get("age"):
        ax.text(indent + 1.1, i + 0.72, c["age"], va="center",
                fontproperties=f_reg, fontsize=7.5, color="#5a584f")
    ax.text(9.95, i + 0.5, f"{c['key']}  {c['color']}", va="center", ha="right",
            fontproperties=f_reg, fontsize=7.5, color="#5a584f")
plt.savefig("geology_classes_preview.png", facecolor=fig.get_facecolor(),
            bbox_inches="tight", pad_inches=0.2)
print("saved")
