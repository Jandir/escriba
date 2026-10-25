import pytest
from unittest.mock import patch, call
import utils

def test_print_countdown_keyboard_interrupt():
    """Test that KeyboardInterrupt is caught and sys.stdout is cleared correctly"""
    with patch("time.sleep", side_effect=KeyboardInterrupt()), \
         patch("sys.stdout.write") as mock_stdout_write, \
         patch("sys.stdout.flush") as mock_stdout_flush:

        with pytest.raises(KeyboardInterrupt):
            utils.print_countdown(3, "Waiting")

        assert call("\r\x1b[K") in mock_stdout_write.call_args_list
        assert mock_stdout_flush.called
