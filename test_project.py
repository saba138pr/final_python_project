import project
import pytest


def reset_statistics():
    project.total_notifications = 0
    project.total_frames = 0
    project.lost_samples = 0
    project.bad_packets = 0
    project.last_counter = None
    project.first_counter = None

    project.rate_window_start_time = None
    project.rate_window_frames = 0
    project.rate_window_notifications = 0
    project.rate_window_bytes = 0

    project.current_sample_rate_hz = 0.0
    project.current_notification_rate_hz = 0.0
    project.current_throughput_bps = 0.0


def test_get_rate_stats_initial_values():
    reset_statistics()

    sample_rate, notification_rate, throughput = project.get_rate_stats()

    assert sample_rate == 0.0
    assert notification_rate == 0.0
    assert throughput == 0.0


def test_process_frame(monkeypatch):
    reset_statistics()

    saved_data = []

    def fake_save_frame(counter, values):
        saved_data.append((counter, values))

    monkeypatch.setattr(
        project,
        "save_frame_to_csv",
        fake_save_frame
    )

    frame = bytes([
        0, 0, 1,
        0, 0, 2,
        0, 0, 3,
        0, 0, 4,
        0, 0, 5,
        0, 0, 6,
        0, 0, 7,
        0, 0, 8
    ])

    project.process_frame(frame)

    assert project.first_counter == 1
    assert project.last_counter == 1
    assert project.lost_samples == 0

    assert len(saved_data) == 1

    counter, values = saved_data[0]

    assert counter == 1
    assert values == [1, 2, 3, 4, 5, 6, 7, 8]


def test_notification_handler_bad_packet():
    reset_statistics()

    bad_packet = bytes([1, 2, 3, 4, 5])

    project.notification_handler(
        None,
        bad_packet
    )

    assert project.total_notifications == 1
    assert project.bad_packets == 1


def test_notification_handler_valid_packet(monkeypatch):
    reset_statistics()

    processed_frames = []

    def fake_process_frame(frame):
        processed_frames.append(frame)

    monkeypatch.setattr(
        project,
        "process_frame",
        fake_process_frame
    )

    packet = bytes(range(24))

    project.notification_handler(
        None,
        packet
    )

    assert project.total_notifications == 1
    assert project.bad_packets == 0
    assert len(processed_frames) == 1
    assert len(processed_frames[0]) == 24