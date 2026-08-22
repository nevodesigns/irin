"""IRIN engineering specs: what an artifact has to satisfy, as typed data.

Stdlib only, on purpose. The evaluator that consumes these specs needs the CAD
runtime and everything it drags in; the specs themselves need to be readable by
a benchmark runner, a report generator, and a CI check that should not have to
install OpenCascade to parse a JSON file.

    from irinspec import Spec, Size, ValidSolid, Tolerance

    spec = Spec(
        id="calibration-block",
        prompt="100 x 60 x 20 mm block, four 8 mm through-holes, 2 mm top chamfer",
        assertions=(
            ValidSolid(),
            Size(x=100.0, y=60.0, z=20.0, tolerance=Tolerance.symmetric(0.2)),
        ),
    )
"""

from irinspec.assertions import (
    Assertion,
    BoltCircle,
    Bounds,
    ClashCount,
    Distance,
    FeatureSpacing,
    FilletCount,
    BossCount,
    HoleCount,
    EdgeCount,
    FaceCount,
    NoInterference,
    PartCount,
    Size,
    SOURCES,
    SUPPORTED_KINDS,
    ValidSolid,
    assertion_from_dict,
)
from irinspec.errors import SpecError
from irinspec.spec import SUPPORTED_UNITS, Spec, dump_spec, load_spec, load_specs
from irinspec.tolerance import Tolerance

__all__ = [
    "Assertion",
    "BoltCircle",
    "Bounds",
    "ClashCount",
    "Distance",
    "FeatureSpacing",
    "FilletCount",
    "BossCount",
    "HoleCount",
    "EdgeCount",
    "FaceCount",
    "NoInterference",
    "SOURCES",
    "SUPPORTED_KINDS",
    "SUPPORTED_UNITS",
    "Size",
    "PartCount",
    "Spec",
    "SpecError",
    "Tolerance",
    "ValidSolid",
    "assertion_from_dict",
    "dump_spec",
    "load_spec",
    "load_specs",
]
