"""Re:Chord worship/music chatbot package.

OpenAI-powered chat assistant: identifies songs from partial lyrics,
returns lead sheets, analyzes attached audio/URLs, and (from M6) executes
backend tools via natural language.

Phase A keeps everything in-memory; conversation history persists only in
the browser's localStorage. Phase B adds DB persistence (see db/models.py).
"""
