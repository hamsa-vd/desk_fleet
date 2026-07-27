from deskfleet.dev import build_commands


def test_dev_launcher_defines_the_three_expected_commands() -> None:
    commands = build_commands()

    assert [service.name for service in commands] == ["mock_api", "deskfleet", "streamlit"]
    assert commands[0].command[-2:] == ("--port", "8081")
    assert commands[1].command[-2:] == ("--port", "8080")
    assert commands[2].command[:3] == (commands[2].command[0], "-m", "streamlit")
