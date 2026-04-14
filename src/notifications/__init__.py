"""Operator notification layer.

Phase 14: Event-driven notification delivery with Telegram as primary channel.
Workflows emit typed events; the notification service subscribes, formats, and delivers.

Modules:
    events      — event bus and typed notification event models
    types       — Pydantic types for all 8 event categories
    telegram    — async Telegram bot client with retry/dedup
    composer    — alert composer (Tier C LLM or template-based formatting)
    service     — notification service orchestrating event → format → deliver
    repository  — persistence for notification events and delivery records
"""
