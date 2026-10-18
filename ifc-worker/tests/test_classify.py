from pathlib import Path

from worker.pipeline.classify import classify_element, classify_space, is_mapped, load_keywords, material_key
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
    assert material_key([], "IfcSlab", "FLOOR", MAT) == "floor.tile"
    assert material_key([], "IfcSlab", "ROOF", MAT) == "concrete"
    assert material_key(["Unobtainium"], "IfcWall", None, MAT) == "wall.plaster"
    assert not is_mapped(["Unobtainium"], MAT)
    assert is_mapped(["Stud", "Brick"], MAT) and is_mapped([], MAT)
    assert material_key([], "IfcCovering", "CEILING", MAT) == "ceiling.tile"


def test_fire_typed_flow_terminal_uses_predefined_type():
    def ft(pt, name="X"):
        e = el("IfcFlowTerminal", name, pt)
        e.type_class = "IfcFireSuppressionTerminalType"
        return classify_element(e, KW)

    assert ft("HOSEREEL").catalog_key == "extinguisher.hose_reel"
    assert ft("FIREHYDRANT").catalog_key == "extinguisher.hose_reel"
    assert ft("SPRINKLER").catalog_key == "suppression.sprinkler"
    assert ft("BREECHINGINLET") is None


def test_water_predefined_type_before_toilet_keywords():
    c = classify_element(el("IfcSanitaryTerminal", "WC Basin", "WASHHANDBASIN"), KW)
    assert c.catalog_key == "water.sink"
    assert classify_element(el("IfcSanitaryTerminal", "Seat", "WCSEAT"), KW) is None
    assert classify_element(el("IfcSanitaryTerminal", "WC Pan"), KW) is None


def test_english_variants():
    assert classify_element(el("IfcSanitaryTerminal", "Washbasin"), KW).catalog_key == "water.sink"
    assert classify_element(el("IfcSanitaryTerminal", "Bathtub"), KW).catalog_key == "water.bath"
    assert classify_space(SpaceInfo("g", "1", "Staircase", None, None), KW) == "stair"
    assert classify_space(SpaceInfo("g", "1", "Washroom", None, None), KW) == "wc"
    assert material_key(["Wall Tiles"], "IfcWall", None, MAT) == "wall.tile"
    assert material_key(["Paint Matt White"], "IfcWall", None, MAT) != "glass.frosted"
    assert not material_key(["Paint Matt White"], "IfcWall", None, MAT).startswith("glass")
