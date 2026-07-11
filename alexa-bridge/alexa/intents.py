"""Deterministic intent routing for the Alexa bridge. Every request is
verified (see verify.py) before reaching here. A fixed set of intents get
guaranteed, non-LLM behavior — ending a session, confirming/denying a
pending write approval, checking status, starting over — handled directly
against mcp-tools' plain HTTP/MCP surface, intercepted BEFORE the liaison
agent is ever invoked. Only the free-form catch-all intent (AskLiaisonIntent)
reaches the smolagents alexa_liaison agent, via mcp-tools' liaison_turn.

Keeping these deterministic matters most for confirm/deny: the whole point
of mcp-tools' write-approval gate is that a human, not an LLM's guess at
what "yes" means, decides whether a gated action executes."""

import asyncio

from ask_sdk_model import RequestEnvelope

from . import config, mcp_client

_GENERIC_REPROMPT = "What do you need?"


def _plain_response(speech: str, *, reprompt: str = "",
                    should_end_session: bool = False) -> dict:
    response: dict = {
        "outputSpeech": {"type": "PlainText", "text": speech},
        "shouldEndSession": should_end_session,
    }
    if not should_end_session:
        response["reprompt"] = {
            "outputSpeech": {"type": "PlainText",
                             "text": reprompt or _GENERIC_REPROMPT}}
    return {"version": "1.0", "response": response}


def _user_id(envelope: RequestEnvelope) -> str | None:
    session = envelope.session
    if session is not None and session.user is not None:
        return session.user.user_id
    context = envelope.context
    if (context is not None and context.system is not None
            and context.system.user is not None):
        return context.system.user.user_id
    return None


def _slot_value(intent, slot_name: str) -> str:
    slots = intent.slots or {}
    slot = slots.get(slot_name)
    return (slot.value or "").strip() if slot is not None and slot.value else ""


def _parse_status_fields(status_text: str) -> dict:
    return dict(line.split("=", 1) for line in status_text.splitlines()
               if "=" in line)


async def handle(envelope: RequestEnvelope) -> dict:
    request = envelope.request
    request_type = request.object_type

    if request_type == "SessionEndedRequest":
        # Alexa notifying us the session already ended (timeout, error, the
        # user said 'exit'); no response body is read by the device.
        return {"version": "1.0", "response": {}}

    user_id = _user_id(envelope)
    if not user_id:
        return _plain_response(
            "Sorry, I couldn't tell who's asking — try again in a moment.",
            should_end_session=True)

    if request_type == "LaunchRequest":
        return _plain_response(
            "MakerOps is listening — what do you need?")

    if request_type != "IntentRequest":
        return _plain_response("Sorry, I didn't understand that.",
                               should_end_session=True)

    intent = request.intent
    intent_name = intent.name

    if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
        return _plain_response("Okay, goodbye.", should_end_session=True)

    if intent_name == "AMAZON.HelpIntent":
        return _plain_response(
            "Ask me something, or tell me to do a task. Say status to "
            "check on something I'm working on, start over for a fresh "
            "conversation, or goodbye to end.")

    if intent_name == "AMAZON.FallbackIntent":
        return _plain_response(
            "Sorry, I didn't catch that — can you say that again?")

    if intent_name == "CheckStatusIntent":
        return await _handle_status(user_id)

    if intent_name == "ConfirmActionIntent":
        return await _handle_confirm(user_id, approve=True)

    if intent_name == "DenyActionIntent":
        return await _handle_confirm(user_id, approve=False)

    if intent_name == "StartOverIntent":
        await mcp_client.liaison_reset_session(user_id)
        return _plain_response("Okay, starting fresh. What do you need?")

    if intent_name == "AskLiaisonIntent":
        utterance = _slot_value(intent, "Utterance")
        if not utterance:
            return _plain_response(
                "Sorry, I didn't catch that — can you say that again?")
        return await _handle_liaison_turn(user_id, utterance)

    return _plain_response("Sorry, I didn't understand that.")


async def _handle_status(user_id: str) -> dict:
    fields = _parse_status_fields(
        await mcp_client.liaison_session_status(user_id))
    pending_action_id = fields.get("pending_action_id", "")
    # A 'deferred' background job takes priority when present; otherwise
    # fall back to the most recent turn (last_job_id) — this is what lets
    # "check status" work even after the bridge's own poll gave up waiting
    # on a turn that then finished a few seconds later (see mcp-tools'
    # liaison_domain.py / liaison_store.py for why these are two fields).
    job_id = fields.get("pending_job_id", "") or fields.get("last_job_id", "")
    if not job_id and not pending_action_id:
        return _plain_response("Nothing pending — what do you need?")

    parts = []
    if pending_action_id:
        parts.append(f"Action number {pending_action_id} is still waiting "
                     "on your approval — say confirm or deny.")
    if job_id:
        report = await mcp_client.agent_job_result(job_id)
        if report is None:
            parts.append("I'm still working on your last request.")
        else:
            parts.append(report.get("speech") or report.get("summary")
                         or "That finished, but I don't have a summary to read.")
    return _plain_response(" ".join(parts))


async def _handle_confirm(user_id: str, *, approve: bool) -> dict:
    fields = _parse_status_fields(
        await mcp_client.liaison_session_status(user_id))
    action_id = fields.get("pending_action_id", "")
    if not action_id:
        return _plain_response("There's nothing waiting for approval right now.")

    ok = await mcp_client.resolve_approval(
        action_id, "approve" if approve else "reject")
    await mcp_client.liaison_clear_pending_action(user_id)
    if ok:
        return _plain_response(
            f"Okay, {'approved' if approve else 'rejected'}.")
    return _plain_response(
        "Sorry, I couldn't do that — the action may have already expired.")


async def _handle_liaison_turn(user_id: str, utterance: str) -> dict:
    dispatch_result = await mcp_client.liaison_turn(user_id, utterance)
    job_id = mcp_client.extract_object_id(dispatch_result)
    if not job_id:
        return _plain_response(
            "Sorry, something went wrong on my end — try again in a moment.")

    loop = asyncio.get_event_loop()
    deadline = loop.time() + config.TURN_POLL_TIMEOUT_S
    while loop.time() < deadline:
        report = await mcp_client.agent_job_result(job_id)
        if report is not None:
            return _plain_response(report.get("speech") or "Okay.",
                                   reprompt=report.get("reprompt") or "")
        await asyncio.sleep(config.TURN_POLL_INTERVAL_S)

    return _plain_response(
        "I'm still working on that — ask me for a status update in a bit.")
