import json
from sqlalchemy import select, exists
from ..database import SessionLocal
from ..models import BranchInfo, MessageNode
from ..config import EMBEDDING_MODEL, METADATA_MODEL
from .message_nodes import rebuild_context_nodes
from .providers import normalize_ollama_base_url, post_json, provider_reply


def embed_with_ollama(
    text: str,
    model: str = "nomic-embed-text",
    base_url: str | None = None,
) -> list[float]:
    """Get an embedding vector from Ollama's /api/embed endpoint."""
    selected_base_url = normalize_ollama_base_url(base_url)
    data = post_json(
        f"{selected_base_url}/api/embed",
        {
            "model": model,
            "input": text,
        },
    )
    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise RuntimeError("Ollama returned no embeddings.")
    return embeddings[0]


def generate_metadata(
    provider: str,
    text: str,
    model: str,
    base_url: str | None = None,
) -> dict:
    """Generate summary and tags using the chosen provider."""
    prompt = (
        "Analyze the following conversation and extract a short summary (max 10 words) "
        "and a list of 2-4 tags. Return ONLY a valid JSON object in the exact format: "
        '{"summary": "...", "tags": ["tag1", "tag2"]}'
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Conversation:\n{text}"}
    ]
    try:
        print(f"[DEBUG] Requesting metadata generation with provider {provider} model {model}")
        response_text = provider_reply(provider, model, messages, base_url)
        print(f"[DEBUG] Provider response: {response_text}")
        if isinstance(response_text, dict):
            raw_text = response_text.get("content", "")
        else:
            raw_text = str(response_text)
        clean_text = raw_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        start_idx = clean_text.find("{")
        end_idx = clean_text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            clean_text = clean_text[start_idx : end_idx + 1]
        return json.loads(clean_text)
    except Exception as e:
        print(f"[DEBUG] Metadata generation failed: {e}")
        return {}


def build_embedding_text(context_nodes: list) -> str:
    """Concatenate conversation messages into a single text for embedding."""
    parts = []
    for node in context_nodes:
        if node.role == "exchange":
            if node.user_content:
                parts.append(f"User: {node.user_content}")
            if node.assistant_content:
                parts.append(f"Assistant: {node.assistant_content}")
        elif node.role == "merge":
            continue  # Skip merge markers
        elif node.role in ("user", "assistant") and node.content:
            parts.append(f"{node.role.capitalize()}: {node.content}")
    return "\n".join(parts)


def upsert_branch_info(node_id: int, user_id: int, provider: str = "ollama", metadata_model: str | None = None, ollama_base_url: str | None = None):
    """Create or update BranchInfo for a leaf node."""
    if not metadata_model:
        metadata_model = METADATA_MODEL
    from .embeddings import pack_embedding

    with SessionLocal() as db:
        context_nodes = rebuild_context_nodes(db, node_id, user_id)

    embedding_text = build_embedding_text(context_nodes)
    if not embedding_text.strip():
        print(f"[DEBUG] No text to embed for node {node_id}")
        return None

    print(f"[DEBUG] Upserting branch info for node {node_id} with metadata_model {metadata_model}")
    embedding_model = EMBEDDING_MODEL
    try:
        vector = embed_with_ollama(embedding_text, model=embedding_model, base_url=ollama_base_url)
        print(f"[DEBUG] Got embedding for node {node_id} (dim: {len(vector)})")
    except Exception as e:
        # Embedding is best-effort; don't fail the chat request
        print(f"[DEBUG] Embedding failed: {e}")
        vector = None

    metadata = generate_metadata(provider, embedding_text, model=metadata_model, base_url=ollama_base_url)
    summary = metadata.get("summary")
    tags = metadata.get("tags")
    tags_json = json.dumps(tags) if isinstance(tags, list) else None

    with SessionLocal() as db:
        with db.begin():
            info = db.get(BranchInfo, node_id)
            if info is None:
                info = BranchInfo(
                    node_id=node_id,
                    user_id=user_id,
                )
                db.add(info)

            if vector is not None:
                info.embedding = pack_embedding(vector)
                info.embedding_model = embedding_model
                info.embedding_dim = len(vector)
                
            if summary:
                info.summary = summary
            if tags_json:
                info.tags = tags_json

    return node_id


def _is_leaf_node(db, node_id: int) -> bool:
    return not db.scalar(
        select(
            exists().where(MessageNode.parent_id == node_id)
        )
    )


def recommend_merge_candidates(
    current_node_id: int,
    user_id: int,
    threshold: float = 0.70,
    limit: int = 10,
) -> list[dict]:
    """Find branches whose embedding is similar to the current branch."""
    from .embeddings import unpack_embedding, cosine_similarity

    with SessionLocal() as db:
        current_info = db.get(BranchInfo, current_node_id)
        if current_info is None or current_info.embedding is None:
            return []

        current_vec = unpack_embedding(current_info.embedding)

        # Fetch all other BranchInfo rows for this user that have embeddings
        all_infos = list(db.scalars(
            select(BranchInfo)
            .where(BranchInfo.user_id == user_id)
            .where(BranchInfo.node_id != current_node_id)
            .where(BranchInfo.embedding.isnot(None))
        ))

        results = []
        for info in all_infos:
            candidate_vec = unpack_embedding(info.embedding)
            sim = cosine_similarity(current_vec, candidate_vec)
            if sim >= threshold:
                # only leaf nodes are valid merge candidates
                if _is_leaf_node(db, info.node_id):
                    results.append({
                        "node_id": info.node_id,
                        "similarity": round(sim, 4),
                        "summary": info.summary,
                        "tags": json.loads(info.tags) if info.tags else [],
                        "description": info.description,
                        "is_leaf": True
                    })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]
