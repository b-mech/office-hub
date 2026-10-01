from __future__ import annotations

import unittest

from app.core.addresses import normalize_address


class AddressNormalizerTest(unittest.TestCase):
    def test_seed_statement_and_master_spellings_share_key(self) -> None:
        cases = [
            (
                "150 Rosybloom Lane - SPEC",
                "Connection Homes Inc - 150 Rosybloom Ln, Ile des Chenes, MB",
                "150 ROSYBLOOM LANE ILE DES CHENES",
            ),
            (
                "26 / 28 Oak Meadow Dr.",
                "Connection Homes - 26/28 Oak Meadow Drive, Oakbank, MB",
                "26-28 OAK MEADOW DR OAKBANK",
            ),
            (
                "2 Cardinal Way (Full 2027)",
                "Connection Homes Inc Promissory Note 2 Cardinal Way, Landmark, MB",
                "2 CARDINAL WAY LANDMARK",
            ),
            (
                "33 Gleneagles Street - SHOWHOME",
                "33 Gleneagles St., Niverville, MB",
                "33 GLENEAGLES ST NIVERVILLE",
            ),
            (
                "33 Gleneagles Street – SPEC",
                "33 Gleneagles St., Niverville, MB",
                "33 GLENEAGLES ST NIVERVILLE",
            ),
            (
                "64 Woodland Way – SHOWHOME",
                "64 Woodland Way, West St Paul, MB",
                "64 WOODLAND WAY WEST ST PAUL",
            ),
            (
                "122 Ramona Gallos",
                "122 Ramona Gallos Way, Winnipeg, MB",
                "122 RAMONA GALLOS WAY WINNIPEG",
            ),
            (
                "127 Champagne – SPEC",
                "127 Champagne St",
                "127 CHAMPAGNE ST WINNIPEG",
            ),
        ]
        for master, lender, expected in cases:
            self.assertEqual(expected, normalize_address(master).canonical_key)
            self.assertEqual(expected, normalize_address(lender).canonical_key)

    def test_development_keys_are_prefixed(self) -> None:
        self.assertEqual("DEV:TEMPLETON DEV DEPOSIT", normalize_address("Templeton Dev Deposit (Promissory Note)").canonical_key)

    def test_known_sheet_stage_addresses_normalize(self) -> None:
        self.assertEqual("675 COMMUNITY ROW", normalize_address("675 Community Row").canonical_key)
        self.assertEqual("104 LYNNE LANE", normalize_address("104 Lynne Lane").canonical_key)
        self.assertEqual("104 LYNNE LANE", normalize_address("104 Lyne Lane").canonical_key)

    def test_street_first_inventory_addresses_match_number_first(self) -> None:
        cases = [
            ("Boulder Crescent, 3", "3 Boulder Crescent"),
            ("Woodland Way, 49", "49 Woodland Way"),
            (
                "Ramona Gallos Way, 154 (bought from GS Homes)",
                "154 Ramona Gallos Way",
            ),
        ]
        for inventory_address, civic_address in cases:
            self.assertEqual(
                normalize_address(civic_address).canonical_key,
                normalize_address(inventory_address).canonical_key,
            )

    def test_missing_known_suffix_and_status_annotation_normalize(self) -> None:
        self.assertEqual(
            normalize_address("165 Blossom Way").canonical_key,
            normalize_address("165 Blossom").canonical_key,
        )
        self.assertEqual(
            normalize_address("8-100 Grande Pointe Meadows Blvd").canonical_key,
            normalize_address("8-100 Grande Pointe Meadows - ON HOLD").canonical_key,
        )


if __name__ == "__main__":
    unittest.main()
