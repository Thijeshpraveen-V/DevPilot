import json
from pathlib import Path
from agent.history import HistoryManager

def test_history_append_and_get():
    history = HistoryManager()
    msg = {"role": "user", "content": "Hello"}
    history.append(msg)
    assert history.get_messages() == [msg]

def test_history_save_and_load(tmp_path: Path):
    history = HistoryManager()
    msg1 = {"role": "user", "content": "Hello"}
    msg2 = {"role": "assistant", "content": "Hi there"}
    history.extend([msg1, msg2])
    
    file_path = tmp_path / "session.json"
    history.save(file_path)
    assert file_path.exists()
    
    new_history = HistoryManager()
    new_history.load(file_path)
    assert new_history.get_messages() == [msg1, msg2]

def test_history_truncation():
    history = HistoryManager()
    
    # Each message should be somewhat large to force truncation
    large_text = "A" * 100_000
    msg1 = {"role": "user", "content": large_text}
    msg2 = {"role": "assistant", "content": large_text}
    msg3 = {"role": "user", "content": large_text}
    msg4 = {"role": "assistant", "content": large_text}
    msg5 = {"role": "user", "content": large_text}
    
    history.extend([msg1, msg2, msg3, msg4, msg5])
    
    # Because _MAX_CHARS is 400,000, 5 messages of 100k+ chars should exceed it
    # Truncation should drop earlier messages.
    messages = history.get_messages()
    assert len(messages) < 5
    assert len(messages) >= 2 # Should not drop below 2 messages usually
    assert messages[0]["role"] == "user" # First remaining should be a user message
