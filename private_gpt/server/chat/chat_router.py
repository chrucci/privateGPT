from fastapi import APIRouter, Depends
from llama_index.llms import ChatMessage, MessageRole
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from private_gpt.di import root_injector
from private_gpt.open_ai.extensions.context_filter import ContextFilter
from private_gpt.open_ai.openai_models import (
    OpenAICompletion,
    OpenAIMessage,
    to_openai_response,
    to_openai_sse_stream,
)
from private_gpt.server.chat.chat_service import ChatService
from private_gpt.server.utils.auth import authenticated

chat_router = APIRouter(prefix="/v1", dependencies=[Depends(authenticated)])


class ChatBody(BaseModel):
    messages: list[OpenAIMessage]
    use_context: bool = False
    context_filter: ContextFilter | None = None
    include_sources: bool = True
    stream: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "How do you fry an egg?",
                        }
                    ],
                    "stream": False,
                    "use_context": True,
                    "include_sources": True,
                    "context_filter": {
                        "docs_ids": ["c202d5e6-7b69-4869-81cc-dd574ee8ee11"]
                    },
                }
            ]
        }
    }


@chat_router.post(
    "/chat/completions",
    response_model=None,
    responses={200: {"model": OpenAICompletion}},
    tags=["Contextual Completions"],
)
def chat_completion(body: ChatBody) -> OpenAICompletion | StreamingResponse:
    """Given a list of messages comprising a conversation, return a response.

    If `use_context` is set to `true`, the model will use context coming
    from the ingested documents to create the response. The documents being used can
    be filtered using the `context_filter` and passing the document IDs to be used.
    Ingested documents IDs can be found using `/ingest/list` endpoint. If you want
    all ingested documents to be used, remove `context_filter` altogether.

    When using `'include_sources': true`, the API will return the source Chunks used
    to create the response, which come from the context provided.

    When using `'stream': true`, the API will return data chunks following [OpenAI's
    streaming model](https://platform.openai.com/docs/api-reference/chat/streaming):
    ```
    {"id":"12345","object":"completion.chunk","created":1694268190,
    "model":"private-gpt","choices":[{"index":0,"delta":{"content":"Hello"},
    "finish_reason":null}]}
    ```
    """
    service = root_injector.get(ChatService)
    all_messages = [
        ChatMessage(content=m.content, role=MessageRole(m.role)) for m in body.messages
    ]
    if body.stream:
        completion_gen = service.stream_chat(
            all_messages, body.use_context, body.context_filter
        )
        return StreamingResponse(
            to_openai_sse_stream(
                completion_gen.response,
                completion_gen.sources if body.include_sources else None,
            ),
            media_type="text/event-stream",
        )
    else:
        completion = service.chat(all_messages, body.use_context, body.context_filter)
        return to_openai_response(
            completion.response, completion.sources if body.include_sources else None
        )
