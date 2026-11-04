from agos_core.domain.workspace import workspace_id_from_name


def test_ids_from_names() -> None:
    assert workspace_id_from_name("Argan Store 2") == "argan-store-2"
    assert workspace_id_from_name("Café Été") == "cafe-ete"
    assert workspace_id_from_name("!!!") == ""
