#!/usr/bin/python3
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
"""
colorwheel.py
-------------
A simple circular HSV colour-wheel selector for PyDPainter.

Usage (from other modules):

    import libs.colorwheel as colorwheel
    rgb = colorwheel.colorwheel_req(screen, config)
    # rgb is a (r,g,b) tuple of ints 0-255 or None if the user cancelled.

This file defines two things:

1. `ColorWheelGadget` – a Gadget.TYPE_CUSTOM subclass that draws the wheel and
   translates mouse clicks into RGB colours.
2. `colorwheel_req()` – a helper that pops up a small requestor containing the
   wheel gadget.  It blocks until the user clicks a colour or presses Esc/Cancel
   and then returns the selected colour.
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

def _generate_wheel_surface(radius: int) -> pygame.Surface:
    """Return a pygame.Surface (diameter×diameter) rendering of an HSV wheel."""
    diameter = radius * 2
    surf = pygame.Surface((diameter, diameter)).convert()
    centre = radius, radius

    for y in range(diameter):
        for x in range(diameter):
            dx = x - centre[0]
            dy = y - centre[1]
            dist = math.hypot(dx, dy)
            if dist > radius:
                # Outside wheel: transparent mask later
                surf.set_at((x, y), (0, 0, 0))
                continue
            # HSV mapping: hue by angle, saturation by radius, value fixed 1
            hue = (math.atan2(-dy, dx) % (2 * math.pi)) / (2 * math.pi)
            sat = min(1.0, dist / radius)
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            surf.set_at((x, y), (int(r * 255), int(g * 255), int(b * 255)))
    return surf

# Cache to avoid regenerating between openings
_WHEEL_CACHE: dict[int, pygame.Surface] = {}


def _get_wheel_surface(radius: int) -> pygame.Surface:
    if radius not in _WHEEL_CACHE:
        _WHEEL_CACHE[radius] = _generate_wheel_surface(radius)
    return _WHEEL_CACHE[radius]

# -----------------------------------------------------------------------------
# Gadget implementation
# -----------------------------------------------------------------------------
class ColorWheelGadget(Gadget):
    """Custom gadget that displays an HSV colour wheel and reports clicks."""

    def __init__(self, rect, radius: int, id: str = "wheel"):
        super().__init__(Gadget.TYPE_CUSTOM, "wheel", rect, id=id)
        self.radius = radius
        self._wheel_surf = _get_wheel_surface(radius)
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

        # Fill background and blit wheel centred
        screen.fill(bgcolor, self.screenrect)
        wheel_rect = self._wheel_surf.get_rect(center=(x + xo + w // 2, y + yo + h // 2))
        screen.blit(self._wheel_surf, wheel_rect)

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
            # Translate mouse to wheel coordinates
            x, y, w, h = self.screenrect
            cx = x + w // 2
            cy = y + h // 2
            dx = mx - cx
            dy = my - cy
            dist = math.hypot(dx, dy)
            if dist > self.radius:
                return ge  # outside wheel, ignore
            hue = (math.atan2(-dy, dx) % (2 * math.pi)) / (2 * math.pi)
            sat = min(1.0, dist / self.radius)
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            self.value = (int(r * 255), int(g * 255), int(b * 255))
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
