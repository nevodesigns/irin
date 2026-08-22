"""Spacer ring with six holes on a bolt circle."""

import math

from build123d import Align, BuildPart, Cylinder, Location, Locations, Mode

OUTSIDE_DIAMETER = 80.0
BORE = 50.0
THICKNESS = 5.0
BOLT_CIRCLE = 65.0
BOLT_HOLE = 6.0
BOLT_COUNT = 6


def gen_step():
    with BuildPart() as part:
        Cylinder(OUTSIDE_DIAMETER / 2.0, THICKNESS,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(Location((0.0, 0.0, -1.0))):
            Cylinder(BORE / 2.0, THICKNESS + 2.0,
                     align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
        radius = BOLT_CIRCLE / 2.0
        for index in range(BOLT_COUNT):
            angle = 2.0 * math.pi * index / BOLT_COUNT
            with Locations(Location((radius * math.cos(angle), radius * math.sin(angle), -1.0))):
                Cylinder(BOLT_HOLE / 2.0, THICKNESS + 2.0,
                         align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

    solid = part.part
    solid.label = "six_hole_spacer_ring"
    return solid
