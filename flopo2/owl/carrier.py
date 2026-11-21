"""Quality of a whole with respect to its parts (docs/odp/16-quality-of-a-whole-towards-its-parts.md).

"Leaves alternate" names the leaf, but no single leaf is alternate: the shoot axis bears one
leaf at each node. "Sepals connate" names the sepal, but the fusion is a state of the calyx.
The record keeps the part the flora names (``po_id``, with its offsets). The slot ``carrier``
names the structure that has the quality; the OWL class is then

    has part some (carrier and has characteristic some (Q and towards some part))

Two kinds:

* ``arrangement``: how the parts sit on the axis that bears them. The carrier is the shoot axis
  (leaves, branches), the leaf rachis (leaflets, pinnae) or the inflorescence axis (flowers,
  bracts, spikelets). Ellis et al. 2009, Manual of Leaf Architecture, character 2: "Leaf
  arrangement - the placement of adjacent leaves on the nodes of the axis".
* ``set``: a relation among the like members of a floral whorl. The carrier is the calyx,
  corolla, perianth, androecium, gynoecium or involucre.

The carrier is derived from the part by the tables below, never read from the source; a part
that is not in a table keeps the plain pattern 00.
"""

from __future__ import annotations

SHOOT_AXIS = "PO_0025029"
LEAF_RACHIS = "PO_0020055"
INFLORESCENCE_AXIS = "PO_0020122"

# part -> the axis that bears it
AXIS_OF = {
    "PO_0025034": SHOOT_AXIS,  # leaf
    "PO_0009025": SHOOT_AXIS,  # vascular leaf
    "PO_0025073": SHOOT_AXIS,  # branch
    "PO_0020049": LEAF_RACHIS,  # leaflet
    "FLOPO_0985027": LEAF_RACHIS,  # pinna
    "PO_0009046": INFLORESCENCE_AXIS,  # flower
    "PO_0009055": INFLORESCENCE_AXIS,  # bract
    "PO_0009051": INFLORESCENCE_AXIS,  # spikelet
}

# member -> the whorl or set it belongs to
SET_OF = {
    "PO_0009031": "PO_0009060",  # sepal -> calyx
    "PO_0009032": "PO_0009059",  # petal -> corolla
    "PO_0009033": "PO_0009058",  # tepal -> perianth
    "PO_0009029": "PO_0009061",  # stamen -> androecium
    "PO_0009067": "PO_0009061",  # filament -> androecium
    "PO_0009066": "PO_0009061",  # anther -> androecium
    "PO_0009030": "PO_0009062",  # carpel -> gynoecium
    "PO_0009074": "PO_0009062",  # style -> gynoecium
    "PO_0009045": "PO_0009100",  # involucral bract -> involucre
}

ARRANGEMENT_VALUES = {
    "PATO_0001932",  # alternate placement: one part at a node
    "PATO_0001933",  # opposite: two parts at a node
    "PATO_0001951",  # whorled: three or more parts at a node
    "PATO_0001952",  # distichous: in two ranks
    "PATO_0001953",  # decussate: pairs at right angles to the pairs next to them
    "FLOPO_0991114",  # spirally arranged
    "FLOPO_0991146",  # secund: all to one side of the axis
    "PATO_0000619",  # crowded
    "FLOPO_0991189",  # distant
    "FLOPO_0991190",  # approximate
    "FLOPO_0991063",  # imbricate (leaves along an axis)
}

SET_VALUES = {
    "FLOPO_0991067",  # connate
    "FLOPO_0991068",  # free
    "FLOPO_0991101",  # unequal
    "FLOPO_0991102",  # equal
    "FLOPO_0991167",  # didynamous
    "FLOPO_0991259",  # diadelphous
    "FLOPO_0991063",  # imbricate (members of a whorl in bud)
    "FLOPO_0991083",  # valvate
}

KINDS = ("arrangement", "set")

# Slots that give the record another reading; with one of them the plain pattern stays.
_BLOCKING = (
    "towards", "part_restrictions", "bearer_container", "bearer_whole", "bearer_collection",
    "bearer_collection_size", "bearer_scope", "count_position", "count_word", "specimen_condition",
)


def _norm(term: object) -> str:
    return str(term or "").strip().replace(":", "_").rsplit("/", 1)[-1]


def value_of(assertion: dict) -> str | None:
    """The one stated value: the single value term, or the quality when there is none."""

    values = [_norm(v) for v in assertion.get("value_terms") or assertion.get("value_term_ids") or []]
    if len(values) > 1 or (assertion.get("value_operator") or "atomic") != "atomic":
        return None
    return values[0] if values else _norm(assertion.get("pato_id"))


def expected(part: object, value: object) -> dict | None:
    """The carrier for a part and a value, or None: the tables are the whole rule."""

    part, value = _norm(part), _norm(value)
    if value in SET_VALUES and part in SET_OF:
        return {"carrier_term": SET_OF[part], "kind": "set"}
    if value in ARRANGEMENT_VALUES and part in AXIS_OF:
        return {"carrier_term": AXIS_OF[part], "kind": "arrangement"}
    return None


def carrier_for(assertion: dict) -> dict | None:
    """The ``carrier`` slot this assertion should have, or None when the pattern does not apply."""

    if assertion.get("negated") or assertion.get("value_low") is not None or assertion.get("value_high") is not None:
        return None
    if any(assertion.get(slot) for slot in _BLOCKING):
        return None
    value = value_of(assertion)
    return expected(assertion.get("po_id"), value) if value else None


def apply(assertion: dict) -> bool:
    """Set the slot and the class identifier that follows from it. True when the record changed."""

    from flopo2.owl.annotation_class import annotation_class_iri

    slot = carrier_for(assertion)
    if slot is None or assertion.get("carrier") == slot:
        return False
    assertion["carrier"] = slot
    if assertion.get("phenotype_class_iri"):
        assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    return True
