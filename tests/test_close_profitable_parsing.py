import pytest

from scripts.close_profitable_positions import _infer_side_qty


def test_infer_side_qty_prefers_explicit_short():
    pos = {
        "side": "short",
        "contracts": 0.02,
        "info": {
            "position": {"szi": "-0.02"},
        },
    }

    side, qty = _infer_side_qty(pos)

    assert side == "short"
    assert qty == pytest.approx(0.02)


def test_infer_side_qty_uses_sign_when_side_missing():
    pos = {
        "contracts": -0.01,
        "info": {},
    }

    side, qty = _infer_side_qty(pos)

    assert side == "short"
    assert qty == pytest.approx(0.01)
