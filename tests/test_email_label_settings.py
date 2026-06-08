from src.settings import get_setting, _PER_USER_KEYS


def test_label_setting_defaults():
    assert get_setting("email_auto_create_labels") is False
    assert get_setting("email_label_cap") == 50
    assert get_setting("email_label_confidence_min") == 0.7
    assert get_setting("email_label_dedup_cosine") == 0.85
    assert get_setting("email_label_new_per_run") == 3


def test_auto_create_is_per_user():
    assert "email_auto_create_labels" in _PER_USER_KEYS
