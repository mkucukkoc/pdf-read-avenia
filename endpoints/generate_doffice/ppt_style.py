import random
from pptx.dml.color import RGBColor
from pptx.util import Pt


def generate_random_style():
    bg_colors = [
        RGBColor(255, 255, 255),
        RGBColor(240, 248, 255),
        RGBColor(230, 230, 250),
        RGBColor(255, 245, 238),
    ]
    title_colors = [
        RGBColor(91, 55, 183),
        RGBColor(0, 102, 204),
        RGBColor(220, 20, 60),
    ]
    fonts = ["Segoe UI", "Calibri", "Arial", "Verdana"]
    content_fonts = ["Calibri", "Georgia", "Tahoma"]
    font_sizes = [Pt(18), Pt(20), Pt(22)]

    return {
        "bg_color": random.choice(bg_colors),
        "title_color": random.choice(title_colors),
        "title_font": random.choice(fonts),
        "content_font": random.choice(content_fonts),
        "content_font_size": random.choice(font_sizes),
    }


