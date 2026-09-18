from evaluation.verify_day7_e2e_report import DEFAULT_FIXTURES, DEFAULT_REPORT, verify_report


def test_committed_day7_end_to_end_acceptance_evidence() -> None:
    assert verify_report(DEFAULT_REPORT, DEFAULT_FIXTURES) == []
