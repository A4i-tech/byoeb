from byoeb_core.models.vector_stores.chunk import Chunk_metadata


def test_new_fields_default_to_none():
    m = Chunk_metadata(source="doc.pdf", creation_timestamp="0", update_timestamp="0")
    assert m.source_filename is None
    assert m.page_number is None
    assert m.section_heading is None


def test_new_fields_set_correctly():
    m = Chunk_metadata(
        source="doc.pdf",
        source_filename="Pregnancy Health Guide",
        page_number=5,
        section_heading="Nutrition",
        creation_timestamp="1700000000",
        update_timestamp="1700000001",
    )
    assert m.source_filename == "Pregnancy Health Guide"
    assert m.page_number == 5
    assert m.section_heading == "Nutrition"


def test_legacy_metadata_no_new_fields():
    m = Chunk_metadata(source="legacy.pdf")
    assert m.source == "legacy.pdf"
    assert m.source_filename is None
    assert m.page_number is None
    assert m.section_heading is None
