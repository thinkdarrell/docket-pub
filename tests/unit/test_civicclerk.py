"""Unit tests for CivicClerk adapter item flattening."""

from docket.adapters.civicclerk import CivicClerkAdapter


class TestFlattenItems:
    """Tests for CivicClerkAdapter._flatten_items().

    CivicClerk returns hierarchical agenda items with nested childItems.
    The flattener should:
    - Skip section headers (isSection=True or no item number + has children)
    - Recursively include leaf items
    - Strip HTML from names and descriptions
    - Assign sequential indexes
    """

    def setup_method(self):
        self.adapter = CivicClerkAdapter("test", {"tenant": "test", "category_id": 1})

    def _flatten(self, item_list):
        result = []
        self.adapter._flatten_items(item_list, result, "meeting-1", index=0)
        return result

    # --- Basic flattening ---------------------------------------------------

    def test_single_item(self):
        items = [{"id": 1, "agendaObjectItemName": "Roll Call", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "1 Roll Call"
        assert result[0].external_id == "1"
        assert result[0].item_number == "1"

    def test_multiple_items(self):
        items = [
            {"id": 1, "agendaObjectItemName": "Roll Call", "agendaObjectItemNumber": "1"},
            {"id": 2, "agendaObjectItemName": "Pledge", "agendaObjectItemNumber": "2"},
            {"id": 3, "agendaObjectItemName": "Minutes", "agendaObjectItemNumber": "3"},
        ]
        result = self._flatten(items)
        assert len(result) == 3
        assert result[0].title == "1 Roll Call"
        assert result[2].title == "3 Minutes"

    # --- Section headers skipped --------------------------------------------

    def test_section_header_skipped(self):
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Consent Agenda",
                "childItems": [
                    {"id": 10, "agendaObjectItemName": "Item A", "agendaObjectItemNumber": "A"},
                    {"id": 11, "agendaObjectItemName": "Item B", "agendaObjectItemNumber": "B"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 2
        assert result[0].title == "A Item A"
        assert result[1].title == "B Item B"

    def test_implicit_section_skipped(self):
        """Items with no item number but with children are treated as sections."""
        items = [
            {
                "agendaObjectItemName": "New Business",
                "childItems": [
                    {"id": 20, "agendaObjectItemName": "Rezoning", "agendaObjectItemNumber": "1"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "1 Rezoning"

    # --- Nested children ----------------------------------------------------

    def test_deeply_nested(self):
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Section",
                "childItems": [
                    {
                        "isSection": True,
                        "agendaObjectItemName": "Sub-section",
                        "childItems": [
                            {"id": 30, "agendaObjectItemName": "Leaf", "agendaObjectItemNumber": "1.1.1"},
                        ],
                    },
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "1.1.1 Leaf"

    # --- HTML stripping -----------------------------------------------------

    def test_html_stripped(self):
        items = [
            {
                "id": 40,
                "agendaObjectItemName": "<b>Bold Item</b>",
                "agendaObjectItemNumber": "1",
                "description": "<p>Some &amp; description</p>",
            },
        ]
        result = self._flatten(items)
        assert result[0].title == "1 Bold Item"
        assert result[0].description == "Some & description"

    def test_html_entities(self):
        items = [
            {
                "id": 41,
                "agendaObjectItemName": "Item &amp; Thing",
                "agendaObjectItemNumber": "1",
            },
        ]
        result = self._flatten(items)
        assert result[0].title == "1 Item & Thing"

    # --- Description truncation ---------------------------------------------

    def test_long_description_truncated(self):
        items = [
            {
                "id": 50,
                "agendaObjectItemName": "Item",
                "agendaObjectItemNumber": "1",
                "description": "x" * 500,
            },
        ]
        result = self._flatten(items)
        assert len(result[0].description) == 300

    # --- Alternative field names --------------------------------------------

    def test_name_field(self):
        """CivicClerk sometimes uses 'name' instead of 'agendaObjectItemName'."""
        items = [{"id": 60, "name": "Alt Name", "itemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].title == "1 Alt Name"

    def test_children_field(self):
        """Some responses use 'children' instead of 'childItems'."""
        items = [
            {
                "isSection": True,
                "agendaObjectItemName": "Header",
                "children": [
                    {"id": 70, "agendaObjectItemName": "Child", "agendaObjectItemNumber": "1"},
                ],
            },
        ]
        result = self._flatten(items)
        assert len(result) == 1
        assert result[0].title == "1 Child"

    # --- Empty / edge cases -------------------------------------------------

    def test_empty_list(self):
        assert self._flatten([]) == []

    def test_item_without_id_gets_generated_external_id(self):
        items = [{"agendaObjectItemName": "No ID Item", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].external_id == "meeting-1-0"

    def test_meeting_external_id_propagated(self):
        items = [{"id": 80, "agendaObjectItemName": "Item", "agendaObjectItemNumber": "1"}]
        result = self._flatten(items)
        assert result[0].meeting_external_id == "meeting-1"
