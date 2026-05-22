"""
state.py — Estado compartido en memoria (summaries para el monitor).
"""
import collections

summaries: collections.deque = collections.deque(maxlen=50)
