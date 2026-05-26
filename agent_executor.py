"""AgentExecutor bridging Google ADK to a2a-sdk (A2A Protocol v1.0)."""
import asyncio
import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import Message, Part, Role
from google.adk import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from google.genai.errors import ClientError

from agent import GoogleMapsAgent

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [5, 10, 20]  # seconds between retries on 429


class GoogleMapsAgentExecutor(AgentExecutor):
    """Executes Google Maps queries via ADK Gemini agent.

    Accepts plain-text input, routes through Gemini 2.0 Flash with Maps tools,
    and returns a plain-text Message so callers receive result.message.parts[0].text.
    Retries automatically on 429 RESOURCE_EXHAUSTED with backoff.
    """

    APP_NAME: str = "google_maps_agent"
    USER_ID: str = "a2a_user"

    def __init__(self, maps_agent: GoogleMapsAgent) -> None:
        self._runner = Runner(
            app_name=self.APP_NAME,
            agent=maps_agent.agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )
        logger.info("GoogleMapsAgentExecutor initialised")

    async def _get_or_create_session(self, session_id: str):
        session = await self._runner.session_service.get_session(
            app_name=self.APP_NAME,
            user_id=self.USER_ID,
            session_id=session_id,
        )
        if session is None:
            session = await self._runner.session_service.create_session(
                app_name=self.APP_NAME,
                user_id=self.USER_ID,
                session_id=session_id,
                state={},
            )
        return session

    async def _run_with_retry(self, session_id: str, content: genai_types.Content) -> str:
        """Run the ADK agent, retrying up to 3 times on 429 RESOURCE_EXHAUSTED."""
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                logger.warning("Gemini 429 — retrying in %ds (attempt %d)", delay, attempt)
                await asyncio.sleep(delay)
            try:
                response_text = ""
                async for event in self._runner.run_async(
                    user_id=self.USER_ID,
                    session_id=session_id,
                    new_message=content,
                ):
                    if event.is_final_response() and event.content:
                        response_text = "\n".join(
                            p.text
                            for p in event.content.parts
                            if hasattr(p, "text") and p.text
                        )
                return response_text
            except ClientError as exc:
                if exc.status_code == 429:
                    last_exc = exc
                    continue
                raise
        raise last_exc  # all retries exhausted

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Run the user query through the ADK Gemini agent and emit a text Message."""
        query = context.get_user_input()
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        logger.info("ADK executing task_id=%s query=%r", task_id, query[:120])

        session = await self._get_or_create_session(context_id)
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=query)],
        )

        response_text = await self._run_with_retry(session.id, content)

        response_msg = Message(
            role=Role.ROLE_AGENT,
            task_id=task_id,
            context_id=context_id,
            message_id=str(uuid.uuid4()),
            parts=[Part(text=response_text or "No response generated.")],
        )
        await event_queue.enqueue_event(response_msg)
        logger.info("ADK task completed task_id=%s", task_id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Cancel requested task_id=%s (not supported)", context.task_id)
        raise NotImplementedError("Cancellation is not supported for ADK agents")
