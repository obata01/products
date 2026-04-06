from a2a.types import AgentCapabilities, AgentCard, AgentSkill


def build_agent_card(base_url: str) -> AgentCard:
    """A2A AgentCard を生成する.

    Args:
        base_url: エージェントカードに記載する A2A サーバーの公開 URL。
                  例: "http://localhost:8000/a2a"

    Returns:
        A2A プロトコルに準拠した AgentCard。
    """
    return AgentCard(
        name="LangGraph Agent",
        description="LangGraph ベースのエージェント。思考過程をストリーミング配信します。",
        url=base_url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="chat",
                name="チャット",
                description="ユーザーのメッセージに応答します。",
                tags=[],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
