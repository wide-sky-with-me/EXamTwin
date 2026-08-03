from examtwin.config_contract import audit_environment_contract


def test_environment_files_match_the_runtime_contract() -> None:
    assert audit_environment_contract().errors == []
