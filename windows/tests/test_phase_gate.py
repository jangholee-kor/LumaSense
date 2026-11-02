from windows.phase_gate import pending_items


def test_api_only_or_office_monitor_cannot_pass():
    assert pending_items({"target_model": "27B2H2", "api_accepted": True})


def test_physical_acceptance_requires_complete_brightness_and_wake():
    record = {"target_model": "Philips 32M2N8900", "observed_by": "observer", "observed_at": "2026-11-02",
              "display_mode": "SDR", "evidence": "recorded test IDs", "brightness": {"20": "pass", "50": "pass", "80": "pass"},
              "display_off": "pass", "wake_methods": {"execution_state": "pass", "monitor_power": "fail"}}
    assert pending_items(record) == []
    record["brightness"]["80"] = "unverified"
    assert pending_items(record) == ["밝기 80% 실기 관찰"]
