"""Headed drill bushing: a body under a head, bored through the whole length."""

from build123d import Align, BuildPart, Cylinder, Location, Locations, Mode

HEAD_DIAMETER = 24.0
HEAD_THICKNESS = 4.0
BODY_DIAMETER = 16.0
BODY_LENGTH = 20.0
BORE = 8.0


def gen_step():
    total = HEAD_THICKNESS + BODY_LENGTH
    with BuildPart() as part:
        Cylinder(HEAD_DIAMETER / 2.0, HEAD_THICKNESS,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(Location((0.0, 0.0, HEAD_THICKNESS))):
            Cylinder(BODY_DIAMETER / 2.0, BODY_LENGTH,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations(Location((0.0, 0.0, -1.0))):
            Cylinder(BORE / 2.0, total + 2.0,
                     align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

    solid = part.part
    solid.label = "headed_drill_bushing"
    return solid
