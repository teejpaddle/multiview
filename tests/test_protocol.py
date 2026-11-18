import pytest

from mvbridge.protocol import HEADER_SIZE, pack_frame, unpack_frame


def test_header_is_24_bytes():
    assert HEADER_SIZE == 24


def test_round_trip():
    message = pack_frame(7, 1_700_000_000_123, 1152, 536, b"jpegdata")
    header, jpeg = unpack_frame(message)
    assert header == (7, 1_700_000_000_123, 1152, 536, 8)
    assert jpeg == b"jpegdata"


def test_layout_is_little_endian():
    message = pack_frame(1, 2, 3, 4, b"x")
    assert message[:4] == b"MVF1"
    assert message[4:8] == b"\x01\x00\x00\x00"
    assert message[8:16] == b"\x02" + b"\x00" * 7
    assert message[16:18] == b"\x03\x00"
    assert message[18:20] == b"\x04\x00"
    assert message[20:24] == b"\x01\x00\x00\x00"


def test_sequence_wraps():
    header, _ = unpack_frame(pack_frame(2**32 + 5, 0, 1, 1, b""))
    assert header.seq == 5


@pytest.mark.parametrize(
    "message",
    [b"short", b"XXXX" + bytes(20), pack_frame(1, 2, 3, 4, b"abc")[:-1]],
)
def test_malformed_messages_are_rejected(message):
    with pytest.raises(ValueError):
        unpack_frame(message)
