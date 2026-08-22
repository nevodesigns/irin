# irinspec

Typed engineering specs for [IRIN](https://github.com/nevodesigns/irin): what a
generated artifact has to satisfy, expressed as data a machine can check.

A spec pairs the prompt handed to an agent with the assertions its result must
pass. The same object serves a benchmark task, where the assertions are the
answer key, and a production requirement, where they run on every regeneration.
Keeping one shape for both is what lets a benchmark number mean something about
real work.

Stdlib only. A benchmark runner, a report generator and a CI check all parse
specs, and none of them should have to install a CAD kernel to read a JSON file.

## Use

```python
from irinspec import Spec, Size, ValidSolid, Tolerance

spec = Spec(
    id="calibration-block",
    prompt="100 x 60 x 20 mm block, four 8 mm through-holes, 2 mm top chamfer",
    assertions=(
        ValidSolid(),
        Size(x=100.0, y=60.0, z=20.0, tolerance=Tolerance.symmetric(0.2)),
    ),
)
```

The same spec as JSON:

```json
{
  "id": "calibration-block",
  "prompt": "100 x 60 x 20 mm block, four 8 mm through-holes, 2 mm top chamfer",
  "units": "mm",
  "assertions": [
    { "kind": "valid_solid" },
    { "kind": "size", "x": 100.0, "y": 60.0, "z": 20.0, "tolerance": { "symmetric": 0.2 } }
  ]
}
```

## Assertion kinds

Every kind here is one IRIN can measure today, from output the CAD inspection
CLI already produces. `source` names the inspection that answers it, so the
evaluator can pay for each inspection once per spec rather than once per claim.

| Kind | Source | Checks |
| --- | --- | --- |
| `valid_solid` | `validate` | Closed, positive-volume, non-self-intersecting solids |
| `size` | `facts` | Bounding-box extents, any subset of x/y/z |
| `bounds` | `facts` | Where the part sits, not only how big it is |
| `part_count` | `facts` | Number of leaf parts in the assembly tree |
| `face_count` | `facts` | Exact face count, as a regression signal |
| `edge_count` | `facts` | Exact edge count, as a regression signal |
| `no_interference` | `interfere` | No part overlaps another beyond a volume floor |
| `clash_count` | `interfere` | Exactly this many known overlaps, as a measured baseline |
| `hole_count` | `features` | How many holes, optionally of one diameter and through or blind |
| `boss_count` | `features` | External cylinders, the exact way to state a round outer diameter |
| `bolt_circle` | `features` | Holes evenly spaced on a pitch circle of a given diameter |
| `feature_spacing` | `features` | Centre distance between the two features of a given size |
| `fillet_count` | `features` | Blended edges, by radius, concave or convex |
| `distance` | `measure` | Distance between two selector refs along one axis |

`distance` addresses geometry by selector ref, and a ref belongs to one model's
topology tree. That makes it right for checking a model you have, and unusable
in a task spec: an agent's model has entirely different refs. `feature_spacing`
states the same kind of requirement by addressing features by size, so it is
checkable on any model that satisfies it.

## What is deliberately missing

Chamfer size and wall thickness are not here. Nor is
`solid_count`: the only figure the inspection exposes counts leaf occurrences,
which does not catch a failed boolean leaving two disjoint bodies inside one
part, so `part_count` is named for what it actually measures.

Hole count and bolt-circle geometry used to be on this list, and left it when
`irincad.features` learned to recognise cylindrical features. `fillet_count`
left it when edge tangency could tell a blend from an opening. That is the only
way anything joins the table above.

Because a prompt may still say more than the assertions can check, a task can
carry an unchecked clause: the calibration block asks for a 2 mm top chamfer and
nothing measures it. Those clauses stay in the prompts, because removing them
would make the requirements artificially thin, but an agent that ignored one
would still score well on that task.

A schema that accepted `{"kind": "fillet_radius", "value": 2.0}` while nothing
could measure a fillet would produce specs that look rigorous and silently check
nothing. That is worse than having no spec, because it converts an unknown into
a false green. Kinds arrive when their evaluator does, and an unknown kind is a
hard error naming the supported set.

## Tolerances

Three forms, matching how drawings write them:

```python
Tolerance.symmetric(0.2)              # +/- 0.2
Tolerance.asymmetric(0.1, 0.05)       # +0.1 / -0.05
Tolerance.relative_fraction(0.005)    # +/- 0.5% of nominal
```

A bare number in JSON is read as symmetric, since that is the common case.

`excess()` is the number worth reporting on a failure: how far outside the band
the value actually landed. A deviation alone does not say whether it mattered,
because 0.3 inside a 0.5 band is fine and 0.3 inside a 0.1 band is the defect.

## Units

Millimetres only. The CAD runtime models in millimetres, so accepting another
unit would mean either a lie or a silent scale factor applied somewhere
downstream, and every dimensional result would be wrong in a way that still
looked plausible.
