import threading
if not LIVE_SONG.get("on"):
    threading.Thread(target=_live_song_loop, name="live-song", daemon=True).start()
print("live-song started", LIVE_SONG)
