from app.services.extraction.service import extract_legal_description_lots


def test_extracts_and_deduplicates_grouped_legal_lot_descriptions() -> None:
    ocr_text = """
LOTS 1 - 34 BLOCK 1 PLAN 20613 WLTO IN N.E. 1/4 4-13-6 E.P.M. (34 lots)
LOTS 37, 39, 41 BLOCK 1 PLAN 20613 WLTO IN N.E. 1/4 4-13-6 E.P.M. (3 lots)
LOT 44 - 49 BLOCK 1 PLAN 20613 WLTO IN N.E. 1/4 4-13-6 E.P.M. (6 lots)
LOTS 1 - 34 BLOCK 1 PLAN 20613 WLTO IN N.E. 1/4 4-13-6 E.P.M. (34 lots)
"""

    lots = extract_legal_description_lots(ocr_text)

    assert [(lot["lot_number"], lot["block"], lot["plan"]) for lot in lots] == [
        ("1-34", "1", "20613 WLTO"),
        ("37, 39, 41", "1", "20613 WLTO"),
        ("44-49", "1", "20613 WLTO"),
    ]
    assert all(lot["lot_notes"] for lot in lots)
