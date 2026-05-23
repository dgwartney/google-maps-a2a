"""AgentExecutor bridging Google ADK to a2a-sdk 1.0.3 (A2A Protocol v1.0)."""
import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import Part, Task, TaskState, TaskStatus
from google.adk import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from agent import GoogleMapsAgent

logger = logging.getLogger(__name__)


class GoogleMapsAgentExecutor(AgentExecutor):
    """Executes Google Maps queries via ADK Gemini agent.

    Bridges a2a-sdk 1.0.3 (A2A Protocol v1.0) to Google ADK tool-calling.
    All requests are processed by Gemini 2.0 Flash which selects and calls
    the appropriate Google Maps skill, then returns a natural language response.

    Uses the Task + artifacts pattern:
    1. Enqueue Task (TASK_STATE_WORKING) — required before TaskStatusUpdateEvents
    2. Stream ADK response via Runner.run_async()
    3. Add text artifact with the natural language response
    4. Mark task COMPLETED
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
        """Return existing session or create a new one.

        Reuses sessions within the same context_id to enable multi-turn
        conversation continuity.
        """
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

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute a natural language query through the ADK Gemini agent."""
        query = context.get_user_input()
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        # Enqueue Task first — required by a2a-sdk before any TaskStatusUpdateEvent
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task_id, context_id)

        try:
            logger.info("ADK executing task_id=%s query=%r", task_id, query[:80])

            session = await self._get_or_create_session(context_id)
            content = genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=query)],
            )

            response_text = ""
            async for event in self._runner.run_async(
                user_id=self.USER_ID,
                session_id=session.id,
                new_message=content,
            ):
                if event.is_final_response() and event.content:
                    response_text = "\n".join(
                        p.text
                        for p in event.content.parts
                        if hasattr(p, "text") and p.text
                    )

            await updater.add_artifact(
                [Part(text=response_text or "No response generated.")],
                name="response",
            )
            await updater.complete()
            logger.info("ADK task completed task_id=%s", task_id)

        except Exception:
            logger.error("ADK task failed task_id=%s", task_id, exc_info=True)
            await updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel is not supported — ADK sessions complete synchronously."""
        logger.info("Cancel requested task_id=%s (not supported)", context.task_id)
        raise NotImplementedError("Cancellation is not supported for ADK agents")
