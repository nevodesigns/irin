"""Inspection payloads captured from the real CAD CLI.

Recorded by running each command against fixtures in ``models/`` and keeping the
output verbatim. Hand-written shapes would let the evaluator drift away from
what the CLI actually returns while its tests stayed green, which is the exact
failure these tests exist to catch.

Sources:
  models/step/parts/rectangular_calibration_block.step.py   single part
  models/step/assemblies/planetary_gear_stage.step.py       nine-part assembly
"""

from __future__ import annotations

BLOCK = "models/step/parts/rectangular_calibration_block.step.py"
GEARS = "models/step/assemblies/planetary_gear_stage.step.py"


# `inspect validate models/step/parts/rectangular_calibration_block.step.py`
BLOCK_VALIDATE = {
    "ok": True,
    "entry": "models/step/parts/rectangular_calibration_block",
    "occurrenceCount": 1,
    "failureCount": 0,
    "parts": [],
    "errors": [],
}

# `inspect refs <block> --facts`
BLOCK_FACTS = {
    "ok": True,
    "tokens": [
        {
            "token": "models/step/parts/rectangular_calibration_block#",
            "cadPath": "models/step/parts/rectangular_calibration_block",
            "stepPath": "models/step/parts/rectangular_calibration_block.step",
            "summary": {
                "kind": "assembly",
                "occurrenceCount": 2,
                "leafOccurrenceCount": 1,
                "shapeCount": 1,
                "faceCount": 14,
                "edgeCount": 32,
                "vertexCount": 0,
                "bounds": {"min": [-50.0, -30.0, 0.0], "max": [50.0, 30.0, 20.0]},
            },
            "selections": [],
            "warnings": [],
            "entryFacts": {
                "size": [100.0, 60.0, 20.0],
                "extentAxis": "x",
                "center": [0.0, 0.0, 10.0],
                "diag": 118.32159566199232,
                "kind": "assembly",
            },
        }
    ],
    "errors": [],
}

# `inspect interfere <block>`
BLOCK_INTERFERE = {
    "ok": True,
    "entry": "models/step/parts/rectangular_calibration_block",
    "tolerance": 1.0,
    "stats": {
        "occurrences": 1,
        "pairs_total": 0,
        "pairs_tested": 0,
        "pairs_skipped_bbox": 0,
        "pairs_truncated": 0,
    },
    "clashCount": 0,
    "clashes": [],
    "errors": [],
}

# `inspect measure <block> --from '#f4' --to '#f8' --axis z`
# f4 is the z=0 underside, f8 the z=20 top face.
BLOCK_MEASURE_Z = {
    "ok": True,
    "axis": "z",
    "from": {"displaySelector": "f4", "coordinate": 0.0},
    "to": {"displaySelector": "f8", "coordinate": 20.0},
    "measurement": {
        "signedDistance": 20.0,
        "absoluteDistance": 20.0,
        "euclideanDistance": 20.0,
        "vectorRelationship": {"relation": "opposed", "dot": -1.0, "aligned": True},
    },
}

# `inspect measure <block> --from '#f999' --to '#f8' --axis z`
BLOCK_MEASURE_BAD_REF = {
    "ok": False,
    "entry": "models/step/parts/rectangular_calibration_block.step.py",
    "from": "#f999",
    "to": "#f8",
    "errors": [
        {
            "message": (
                "Selector 'f999' did not resolve against "
                "models/step/parts/rectangular_calibration_block."
            )
        }
    ],
}

# `inspect refs <gears> --facts`
GEARS_FACTS = {
    "ok": True,
    "tokens": [
        {
            "token": "models/step/assemblies/planetary_gear_stage#",
            "summary": {
                "kind": "assembly",
                "occurrenceCount": 10,
                "leafOccurrenceCount": 9,
                "shapeCount": 9,
                "faceCount": 579,
                "edgeCount": 1683,
                "vertexCount": 0,
                "bounds": {
                    "min": [-70.0, -69.804266, -5.0],
                    "max": [70.0, 69.804266, 9.0],
                },
            },
            "entryFacts": {
                "size": [140.0, 139.608532, 14.0],
                "extentAxis": "x",
                "center": [0.0, 0.0, 2.0],
                "diag": 198.2083303173583,
                "kind": "assembly",
            },
        }
    ],
    "errors": [],
}

# `inspect validate <gears>`
GEARS_VALIDATE = {
    "ok": True,
    "entry": "models/step/assemblies/planetary_gear_stage",
    "occurrenceCount": 9,
    "failureCount": 0,
    "parts": [],
    "errors": [],
}


# --- synthesized failure payloads -------------------------------------------
# Same field shapes as the captured passes above, with the values a defective
# model would produce. Building these by hand is safe precisely because the
# shape is pinned by the recordings.

INVERTED_SOLID_VALIDATE = {
    "ok": False,
    "entry": "models/step/parts/broken",
    "occurrenceCount": 2,
    "failureCount": 1,
    "parts": [
        {
            "ref": "o1.2",
            "name": "lid",
            "reasons": ["nonPositiveVolume"],
            "solidCount": 1,
            "volumes": [-12500.0],
        }
    ],
    "errors": [],
}

CLASHING_INTERFERE = {
    # ok is false whenever clashes exist, with errors empty. That combination is
    # what tells the evaluator this is a defect rather than a broken command.
    "ok": False,
    "entry": "models/step/assemblies/rover",
    "tolerance": 1.0,
    "stats": {"occurrences": 4, "pairs_total": 6, "pairs_tested": 3},
    "clashCount": 2,
    "clashes": [
        {
            "a": {"ref": "o1.1", "name": "wheel_left"},
            "b": {"ref": "o1.3", "name": "chassis"},
            "volume": 812.4,
        },
        {
            "a": {"ref": "o1.2", "name": "motor"},
            "b": {"ref": "o1.3", "name": "chassis"},
            "volume": 45.1,
        },
    ],
    "errors": [],
}

INSPECTION_CRASHED = {
    "ok": False,
    "errors": [{"message": "generation failed: ValueError: bad radius"}],
}


# `inspect features models/step/parts/rectangular_calibration_block.step.py`
# Four 8 mm through-holes at the corners of a rectangle. The pattern fits a
# circle perfectly and is NOT evenly spaced, which is why `uniform` exists.
BLOCK_FEATURES = {
    "ok": True,
    "entry": "models/step/parts/rectangular_calibration_block",
    "occurrenceCount": 1,
    "holeCount": 4,
    "bossCount": 0,
    "features": [
        {
            "ref": "o1",
            "name": "rectangular_calibration_block",
            "kind": "hole",
            "diameter": 8.0,
            "radius": 4.0,
            "axis": [0.0, 0.0, 1.0],
            "position": [x, y, 0.0],
            "depth": 20.0,
            "through": True,
            "complete": True,
            "faceCount": 1,
        }
        for x, y in ((-35.0, -20.0), (-35.0, 20.0), (35.0, -20.0), (35.0, 20.0))
    ],
    "patterns": [
        {
            "holeDiameter": 8.0,
            "count": 4,
            "circleDiameter": 80.622577,
            "center": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0],
            "uniform": False,
            "maxRadiusDeviation": 0.0,
        }
    ],
    "errors": [],
}

# `inspect features models/step/parts/keyed_shaft_hub.step.py`
# A hub: one external cylinder (boss), a keyed bore reported as an incomplete
# cylinder, and four M5 clearance holes on a genuine 39 mm bolt circle.
HUB_FEATURES = {
    "ok": True,
    "entry": "models/step/parts/keyed_shaft_hub",
    "occurrenceCount": 1,
    "holeCount": 5,
    "bossCount": 1,
    "features": [
        {
            "ref": "o1", "name": "hub", "kind": "boss", "diameter": 54.0, "radius": 27.0,
            "axis": [0.0, 0.0, 1.0], "position": [0.0, 0.0, 0.7], "depth": 20.6,
            "through": False, "complete": True, "faceCount": 1,
        },
        {
            "ref": "o1", "name": "hub", "kind": "hole", "diameter": 20.0, "radius": 10.0,
            "axis": [0.0, 0.0, 1.0], "position": [0.0, 0.0, 0.7], "depth": 20.6,
            "through": True, "complete": False, "faceCount": 1,
        },
    ] + [
        {
            "ref": "o1", "name": "hub", "kind": "hole", "diameter": 5.5, "radius": 2.75,
            "axis": [0.0, 0.0, 1.0], "position": [x, y, 0.7], "depth": 20.6,
            "through": True, "complete": True, "faceCount": 1,
        }
        for x, y in (
            (-13.788582, -13.788582), (-13.788582, 13.788582),
            (13.788582, -13.788582), (13.788582, 13.788582),
        )
    ],
    "patterns": [
        {
            "holeDiameter": 5.5,
            "count": 4,
            "circleDiameter": 39.0,
            "center": [0.0, 0.0, 0.7],
            "axis": [0.0, 0.0, 1.0],
            "uniform": True,
            "maxRadiusDeviation": 0.0,
        }
    ],
    "errors": [],
}
