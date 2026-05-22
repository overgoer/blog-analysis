
"""
Honcho memory integration for BSA - memory as a tool pattern.

All messages are stored automatically in Honcho sessions.
BSA can use recall tool to query past conversations via semantic search.
"""

import logging
import os

HONCHO_BASE_URL = os.environ.get("HONCHO_URL", "http://127.0.0.1:8001")
WORKSPACE_ID = "blog-analysis"

_honcho = None
_user_peer = None
_agent_peer = None

logger = logging.getLogger("honcho_memory")


def _get_client():
    global _honcho
    if _honcho is not None:
        return _honcho
    try:
        from honcho import Honcho
        _honcho = Honcho(
            workspace_id=WORKSPACE_ID,
            base_url=HONCHO_BASE_URL,
        )
        logger.info("honcho initialized workspace=%s", WORKSPACE_ID)
    except Exception as e:
        logger.warning("honcho init failed: %s", e)
        _honcho = False
    return _honcho


def _get_peers():
    global _user_peer, _agent_peer
    client = _get_client()
    if not client:
        return None, None
    if _user_peer is None:
        try:
            _user_peer = client.peer("eddy")
            _agent_peer = client.peer("bsa")
        except Exception as e:
            logger.warning("honcho peer init failed: %s", e)
            return None, None
    return _user_peer, _agent_peer


def get_session(chat_id):
    client = _get_client()
    if not client:
        return None
    try:
        return client.session(f"tg-{chat_id}")
    except Exception as e:
        logger.debug("honcho session error: %s", e)
        return None


def save_message(chat_id, role, content):
    client = _get_client()
    if not client:
        return False
    try:
        session = get_session(chat_id)
        user_peer, agent_peer = _get_peers()
        if not session or not user_peer or not agent_peer:
            return False
        peer = user_peer if role == "user" else agent_peer
        session.add_messages([peer.message(content)])
        return True
    except Exception as e:
        logger.debug("honcho save_message error: %s", e)
        return False


def recall(chat_id, question, max_results=3):
    client = _get_client()
    if not client:
        return []
    try:
        session = get_session(chat_id)
        if not session:
            return []
        results = session.search(query=question)
        if not results:
            return []
        snippets = []
        for r in results[:max_results]:
            if hasattr(r, "content") and r.content:
                snippets.append(r.content[:500])
        return snippets
    except Exception as e:
        logger.debug("honcho recall error: %s", e)
        return []


def get_user_card(chat_id):
    client = _get_client()
    if not client:
        return ""
    try:
        session = get_session(chat_id)
        user_peer, _ = _get_peers()
        if not session or not user_peer:
            return ""
        ctx = session.context(
            summary=False,
            peer_target="eddy",
            limit_to_session=True,
            tokens=1000,
        )
        if ctx and ctx.peer_representation:
            return ctx.peer_representation
        return ""
    except Exception as e:
        logger.debug("honcho get_user_card error: %s", e)
        return ""
