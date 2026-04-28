from a2a.types import AgentCapabilities, AgentCard, AgentSkill


def build_claude_code_agent_card(base_url: str) -> AgentCard:
    """Claude Code エージェントの AgentCard を生成する.

    Args:
        base_url: エージェントカードに記載する A2A サーバーの公開 URL.

    Returns:
        A2A プロトコルに準拠した AgentCard.
    """
    return AgentCard(
        name="Claude Code Agent",
        description="Claude Code を利用したエージェント。ストリーミングでテキスト生成を行います。",
        url=base_url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="generate",
                name="テキスト生成",
                description="Claude Code を使用してテキスト生成・ライティングを行います。",
                tags=["writing", "generation", "claude-code"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
