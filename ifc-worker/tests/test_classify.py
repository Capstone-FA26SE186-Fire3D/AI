from pathlib import Path

from worker.pipeline.classify import classify_element, classify_space, load_keywords, material_key
from worker.pipeline.extract import Element, SpaceInfo

CFG = Path(__file__).parent.parent / "config"
KW = load_keywords(CFG / "keywords.v1.json")
MAT = load_keywords(CFG / "materials.v1.json")


def el(ifc_class, name="", predefined=None, psets=None, type_name=None, object_type=None, long_name=None):
    return Element("g", ifc_class, name, long_name, object_type, type_name, predefined, None, psets or {}, [])


def test_extinguisher_proxy_low_confidence():
    c = classify_element(el("IfcBuildingElementProxy", "Fire Extinguisher"), KW)
    assert (c.catalog_key, c.confidence) == ("extinguisher.portable", 0.7)


def test_sink_is_water_source_toilet_is_not():
    assert classify_element(el("IfcSanitaryTerminal", "Sink"), KW).catalog_key == "water.sink"
    assert classify_element(el("IfcSanitaryTerminal", "Toilet"), KW) is None
    assert classify_element(el("IfcSanitaryTerminal", "Water Closet"), KW) is None
    assert classify_element(el("IfcSanitaryTerminal", "Shower Tray"), KW).catalog_key == "water.shower"


def test_external_door_inferred_exit():
    c = classify_element(el("IfcDoor", "Main", psets={"Pset_DoorCommon": {"IsExternal": True}}), KW)
    assert (c.catalog_key, c.confidence, c.source) == ("door.exit", 0.7, "inferred")
    c = classify_element(el("IfcDoor", "X", psets={"Pset_DoorCommon": {"FireExit": True}}), KW)
    assert (c.catalog_key, c.confidence, c.source) == ("door.exit", 0.95, "ifc")
    assert classify_element(el("IfcDoor", "Notausgang"), KW).catalog_key == "door.exit"
    fr = {"Pset_DoorCommon": {"FireRating": "EI30"}}
    assert classify_element(el("IfcDoor", "D", psets=fr), KW).catalog_key == "door.fire"
    assert classify_element(el("IfcDoor", "D"), KW).catalog_key == "door.standard"


def test_occupancy_sensor_not_detector():
    assert classify_element(el("IfcSensor", "Occupancy Sensor", "MOVEMENTSENSOR"), KW) is None
    assert classify_element(el("IfcSensor", "S", "SMOKESENSOR"), KW).catalog_key == "alarm.detector"
    assert classify_element(el("IfcAlarm", "Manual Call Point"), KW).catalog_key == "alarm.call_point"


def test_whole_token_keywords():
    assert classify_element(el("IfcBuildingElementProxy", "Bathroom Cabinet"), KW) is None
    assert classify_element(el("IfcBuildingElementProxy", "Bath"), KW).catalog_key == "water.bath"


def test_sprinkler_and_elevator():
    c = classify_element(el("IfcFireSuppressionTerminal", "X", "SPRINKLER"), KW)
    assert (c.catalog_key, c.confidence) == ("suppression.sprinkler", 0.95)
    assert classify_element(el("IfcTransportElement", "Lift 1"), KW).catalog_key == "transport.elevator"


def test_classify_space():
    assert classify_space(SpaceInfo("g", "101", "Corridor", None, None), KW) == "corridor"
    assert classify_space(SpaceInfo("g", "WC", None, None, None), KW) == "wc"
    assert classify_space(SpaceInfo("g", "5", "Office", None, None), KW) is None


def test_material_ceiling_before_tile():
    assert material_key(["Ceiling tile"], "IfcCovering", None, MAT) == "ceiling.tile"
    assert material_key(["Akustik Fliesen"], "IfcCovering", None, MAT) == "ceiling.tile"
    assert material_key(["Fliesen"], "IfcSlab", "FLOOR", MAT) == "floor.tile"
    assert material_key(["Stud", "Brick"], "IfcWall", None, MAT) == "wall.brick"
    assert material_key([], "IfcSlab", "FLOOR", MAT) == "floor"
    assert material_key([], "IfcSlab", "ROOF", MAT) == "roof"
    assert material_key(["Unobtainium"], "IfcWall", None, MAT) is None
