#!/usr/bin/python3
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
"""
colorwheel.py
-------------
A colour selector gadget supporting multiple shapes (circle/triangle/square)
for picking Hue/Saturation. Value (brightness) is controlled externally.

Usage (from other modules):

    from libs.colorwheel import ColorWheelGadget
    g = ColorWheelGadget((x, y, w, h), radius=80, shape="circle")

This file defines two things:

1. `ColorWheelGadget` – a Gadget.TYPE_CUSTOM subclass that draws the selector
   and translates mouse clicks into RGB colours (with V=1.0).
2. `colorwheel_req()` – a helper that pops up a small requestor containing the
   gadget.  It blocks until the user clicks a colour or presses Esc/Cancel and
   then returns the selected colour.
"""
from __future__ import annotations

import math
import colorsys
from typing import Optional, Tuple

import contextlib
with contextlib.redirect_stdout(None):
    import pygame
    from pygame.locals import *

from libs.gadget import Gadget, Requestor, GadgetEvent, str2req

# -----------------------------------------------------------------------------
# Helper – generate a pre-rendered wheel surface so drawing is fast
# -----------------------------------------------------------------------------

_EDGE_EPS = 0.5  # small safety to avoid fringe/stray pixels
# Barycentric-based equilateral triangle, pointing down.
# Vertices relative to center (0,0) for a triangle inscribed in a circle of radius R:
# Top-left (Blue):     (-R*sqrt(3)/2, -R/2)
# Top-right (Red):     ( R*sqrt(3)/2, -R/2)
# Bottom (Green):      (0, R)
_SQRT3 = math.sqrt(3.0)

def _rmax_square(radius: int, ang: float) -> float:
    # Intersection with axis-aligned square of half-size = radius
    c = math.cos(ang)
    s = math.sin(ang)
    denom = max(abs(c), abs(s)) or 1.0
    return max(0.0, radius / denom)


def _generate_surface(radius: int, shape: str) -> pygame.Surface:
    """Return a pygame.Surface (diameter×diameter) rendering of an HSV selector.

    Note: uses per-pixel alpha; outside the shape is transparent to avoid
    visible black edges around the selector.
    """
    diameter = radius * 2
    surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA).convert_alpha()
    cx, cy = radius, radius
    for y in range(diameter):
        for x in range(diameter):
            dx = x - cx
            dy = y - cy
            if shape == "triangle":
                # Equilateral triangle pointing down, inscribed in circle of radius R
                # Vertices (in screen coords, relative to center cx,cy):
                v1 = (0, radius)  # Green (bottom)
                v2 = (-radius * _SQRT3 / 2, -radius / 2)  # Blue (top-left)
                v3 = (radius * _SQRT3 / 2, -radius / 2)  # Red (top-right)

                # Barycentric coordinates calculation
                denom = (v2[1] - v3[1]) * (v1[0] - v3[0]) + (v3[0] - v2[0]) * (v1[1] - v3[1])
                if abs(denom) < 1e-10:
                    surf.set_at((x, y), (0, 0, 0, 0))
                    continue
                    
                w1 = ((v2[1] - v3[1]) * (dx - v3[0]) + (v3[0] - v2[0]) * (dy - v3[1])) / denom
                w2 = ((v3[1] - v1[1]) * (dx - v3[0]) + (v1[0] - v3[0]) * (dy - v3[1])) / denom
                w3 = 1.0 - w1 - w2

                if 0 <= w1 <= 1 and 0 <= w2 <= 1 and 0 <= w3 <= 1:
                    # Direct RGB mixing using barycentric coordinates
                    # v1=Green, v2=Blue, v3=Red
                    # When all weights are equal (center), we want white, not black
                    r = w3 * 255  # Red component from red vertex
                    g = w1 * 255  # Green component from green vertex  
                    b = w2 * 255  # Blue component from blue vertex
                    
                    surf.set_at((x, y), (int(r), int(g), int(b), 255))
                else:
                    surf.set_at((x, y), (0, 0, 0, 0))
                continue

            # circle / square
            ang = math.atan2(dy, dx)
            r = math.hypot(dx, dy)
            if shape == "circle":
                rmax = float(radius)
            else:  # square
                rmax = _rmax_square(radius, ang)
            if r <= rmax + 1e-6:
                hue = (math.atan2(-dy, dx) % (2 * math.pi)) / (2 * math.pi)
                sat = 0.0 if rmax == 0 else min(1.0, r / rmax)
                rr, gg, bb = colorsys.hsv_to_rgb(hue, sat, 1.0)
                surf.set_at((x, y), (int(rr * 255), int(gg * 255), int(bb * 255), 255))
            else:
                surf.set_at((x, y), (0, 0, 0, 0))
    return surf

# Cache to avoid regenerating between openings, keyed by (shape, radius)
_SURF_CACHE: dict[tuple[str, int], pygame.Surface] = {}


def _get_surface(radius: int, shape: str) -> pygame.Surface:
    key = (shape, radius)
    if key not in _SURF_CACHE:
        _SURF_CACHE[key] = _generate_surface(radius, shape)
    return _SURF_CACHE[key]

# -----------------------------------------------------------------------------
# Gadget implementation
# -----------------------------------------------------------------------------
class ColorWheelGadget(Gadget):
    """Custom gadget that displays an HSV selector (circle/triangle/square)."""

    def __init__(self, rect, radius: int, id: str = "wheel", shape: str = "circle"):
        super().__init__(Gadget.TYPE_CUSTOM, "wheel", rect, id=id)
        self.radius = radius
        self.shape = shape if shape in ("circle", "triangle", "square") else "circle"
        self._surf = _get_surface(radius, self.shape)
        self.need_redraw = True

    def set_shape(self, shape: str):
        if shape not in ("circle", "triangle", "square"):
            return
        if shape != self.shape:
            self.shape = shape
            self._surf = _get_surface(self.radius, self.shape)
            self.need_redraw = True

    def draw(self, screen, font, offset=(0, 0), fgcolor=(0, 0, 0),
             bgcolor=(160, 160, 160), hcolor=(208, 208, 224)):
        self.visible = True
        x, y, w, h = self.rect
        xo, yo = offset
        self.offsetx = xo
        self.offsety = yo
        self.screenrect = (x + xo, y + yo, w, h)

        if not self.need_redraw:
            return
        self.need_redraw = False

        # Fill background and blit selector centred
        screen.fill(bgcolor, self.screenrect)
        wheel_rect = self._surf.get_rect(center=(x + xo + w // 2, y + yo + h // 2))
        screen.blit(self._surf, wheel_rect)

        # Draw current selection marker if we have a value
        try:
            if isinstance(self.value, tuple) and len(self.value) == 3:
                r, g, b = self.value
                # Convert to HSV to compute marker position
                hr, sg, vb = [c / 255.0 for c in (r, g, b)]
                hue, sat, _ = colorsys.rgb_to_hsv(hr, sg, vb)
                # Center and shape radius function in screen coords
                cx = x + xo + w // 2
                cy = y + yo + h // 2
                ang = hue * 2 * math.pi
                if self.shape == "triangle":
                    # Convert RGB back to barycentric coordinates for marker position
                    r, g, b = self.value
                    r_norm = r / 255.0
                    g_norm = g / 255.0  
                    b_norm = b / 255.0
                    
                    # Normalize RGB to get barycentric weights
                    total = r_norm + g_norm + b_norm
                    if total > 0:
                        w1 = g_norm / total  # Green weight
                        w2 = b_norm / total  # Blue weight
                        w3 = r_norm / total  # Red weight
                    else:
                        w1 = w2 = w3 = 1.0/3.0

                    # Triangle vertices (relative to center)
                    v1 = (0, self.radius)  # Green (bottom)
                    v2 = (-self.radius * _SQRT3 / 2, -self.radius / 2)  # Blue (top-left)
                    v3 = (self.radius * _SQRT3 / 2, -self.radius / 2)  # Red (top-right)

                    # Interpolate position using barycentric coordinates
                    pos_x = v1[0] * w1 + v2[0] * w2 + v3[0] * w3
                    pos_y = v1[1] * w1 + v2[1] * w2 + v3[1] * w3

                    mx = int(round(cx + pos_x))
                    my = int(round(cy + pos_y))
                else:
                    if self.shape == "circle":
                        rmax = float(self.radius)
                    else:
                        rmax = _rmax_square(self.radius, ang)
                    rad = max(0.0, min(sat * rmax, max(0.0, rmax - 1.0)))
                    mx = int(round(cx + math.cos(ang) * rad))
                    my = int(round(cy - math.sin(ang) * rad))
                # Marker: black outer, white inner for contrast
                pygame.draw.circle(screen, (0, 0, 0), (mx, my), 4)
                pygame.draw.circle(screen, (255, 255, 255), (mx, my), 2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event processing – when user clicks inside the wheel we set self.value
    # to the selected RGB tuple and emit a GADGETUP event so parents can act.
    # ------------------------------------------------------------------
    def process_event(self, screen, event, mouse_pixel_mapper):
        ge = []
        if event.type not in (MOUSEBUTTONDOWN, MOUSEBUTTONUP):
            return ge

        mx, my = mouse_pixel_mapper()
        if not self.pointin((mx, my), self.screenrect):
            return ge

        if event.type == MOUSEBUTTONDOWN and event.button == 1:
            # Translate mouse to selector coordinates
            x, y, w, h = self.screenrect
            cx = x + w // 2
            cy = y + h // 2
            dx = mx - cx
            dy = my - cy
            if self.shape == "triangle":
                # Equilateral triangle pointing down
                v1 = (0, self.radius)  # Green (bottom)
                v2 = (-self.radius * _SQRT3 / 2, -self.radius / 2)  # Blue (top-left)
                v3 = (self.radius * _SQRT3 / 2, -self.radius / 2)  # Red (top-right)

                # Barycentric coordinates from click
                denom = (v2[1] - v3[1]) * (v1[0] - v3[0]) + (v3[0] - v2[0]) * (v1[1] - v3[1])
                if abs(denom) < 1e-10:
                    return ge
                    
                w1 = ((v2[1] - v3[1]) * (dx - v3[0]) + (v3[0] - v2[0]) * (dy - v3[1])) / denom
                w2 = ((v3[1] - v1[1]) * (dx - v3[0]) + (v1[0] - v3[0]) * (dy - v3[1])) / denom
                w3 = 1.0 - w1 - w2

                if not (0 <= w1 <= 1 and 0 <= w2 <= 1 and 0 <= w3 <= 1):
                    return ge # Outside triangle

                # Direct RGB from barycentric coordinates
                # v1=Green, v2=Blue, v3=Red
                r = int(w3 * 255)  # Red component from red vertex
                g = int(w1 * 255)  # Green component from green vertex
                b = int(w2 * 255)  # Blue component from blue vertex

            else: # Circle or Square
                dist = math.hypot(dx, dy)
                ang = math.atan2(dy, dx)
                if self.shape == "circle":
                    rmax = float(self.radius)
                else:
                    rmax = _rmax_square(self.radius, ang)

                if dist > max(0.0, rmax - 0.5):
                    return ge  # outside selector, ignore

                hue = (math.atan2(-dy, dx) % (2 * math.pi)) / (2 * math.pi)
                denom = rmax if rmax > 1e-6 else 1.0
                sat = max(0.0, min(1.0, dist / denom))
                r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
                r, g, b = int(r * 255), int(g * 255), int(b * 255)
            
            self.value = (r, g, b)
            # Emit immediate GADGETUP so parent can read value and close
            ge.append(GadgetEvent(GadgetEvent.TYPE_GADGETUP, event, self))
        return ge


# -----------------------------------------------------------------------------
# Requestor wrapper – modal colour wheel picker
# -----------------------------------------------------------------------------

def colorwheel_req(screen, config, initial_rgb: Tuple[int, int, int] | None = None) -> Optional[Tuple[int, int, int]]:
    """Display the colour wheel and return the RGB tuple selected, or None."""
    # Build a simple requestor: title "Colour Wheel", size 220×240 or so.
    radius = 88  # 10% smaller
    wheel_size = radius * 2
    req_w = wheel_size + 16
    req_h = wheel_size + 40  # room for border/title
    req_rect = ((screen.get_width() - req_w) // 2,
                (screen.get_height() - req_h) // 2,
                req_w, req_h)

    req = Requestor("Colour Wheel", req_rect, mouse_pixel_mapper=config.get_mouse_pointer_pos, font=config.font)
    # Temporarily override pixel_req_rect so main redraws include the wheel area
    prr_backup = getattr(config, "pixel_req_rect", None)
    config.pixel_req_rect = req.get_screen_rect()
    wheel_rect = (8, 8 + req.fonty, wheel_size, wheel_size)
    wheel_gadget = ColorWheelGadget(wheel_rect, radius)
    req.add(wheel_gadget)

    # Buttons OK / Cancel beneath the wheel
    ok_rect = (req_w // 4 - 30, wheel_rect[1] + wheel_size + 4, 60, req.fonty)
    cancel_rect = (3 * req_w // 4 - 30, wheel_rect[1] + wheel_size + 4, 60, req.fonty)
    ok_g = Gadget(Gadget.TYPE_BOOL, "OK", ok_rect)
    cancel_g = Gadget(Gadget.TYPE_BOOL, "Cancel", cancel_rect)
    req.add(ok_g)
    req.add(cancel_g)

    if initial_rgb is not None:
        wheel_gadget.value = initial_rgb

    req.draggable = True
    # Redraw full application once, then draw wheel on top
    config.recompose()
    screen.set_clip(None)
    req.draw(screen)
    pygame.display.update()

    selected: Optional[Tuple[int, int, int]] = None
    running = True
    while running:
        event = config.xevent.wait()
        gevents = req.process_event(screen, event)
        for ge in gevents:
            if ge.type == GadgetEvent.TYPE_GADGETUP:
                if ge.gadget == wheel_gadget and isinstance(wheel_gadget.value, tuple):
                    selected = wheel_gadget.value
                    running = False
                    break
                if ge.gadget == ok_g:
                    # If OK pressed without clicking wheel, use last selected or initial.
                    if wheel_gadget.value is not None:
                        selected = wheel_gadget.value
                    running = False
                    break
                if ge.gadget == cancel_g:
                    selected = None
                    running = False
                    break
        # Always redraw background first so wheel stays above & ensure no clipping
        config.recompose()
        screen.set_clip(None)
        req.draw(screen)
        pygame.display.update()

    # Restore previous pixel_req_rect and redraw
    config.pixel_req_rect = prr_backup
    config.recompose()
    return selected
